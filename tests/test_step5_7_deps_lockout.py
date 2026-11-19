"""Step 5.7: dependency audit gate, exact pins, security.txt and the account-lockout behaviour.

The tool tests need no network: pip-audit's JSON report is faked. The real audit runs in CI (job `audit`).
"""
import importlib.util
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.models import AuditLog, LoginLockout, User
from app.models.base import utcnow
from tests.helpers import PW, make_user, post

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 18)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit = _load("audit_deps")
pins = _load("pin_requirements")


# ------------------------------------------------------------------ audit gate
def report(*vulns, name="pillow", version="12.0.0"):
    return {"dependencies": [{"name": name, "version": version, "vulns": list(vulns)}, {"name": "flask", "version": "3.1.3", "vulns": []}]}


VULN = {"id": "PYSEC-2026-1", "aliases": ["CVE-2026-0001", "GHSA-aaaa-bbbb-cccc"], "fix_versions": ["13.0.0"]}


def test_clean_report_passes():
    assert audit.evaluate(report(), {}, TODAY) == ([], [])


def test_any_vulnerability_fails_and_names_the_fix():
    failures, accepted = audit.evaluate(report(VULN), {}, TODAY)
    assert accepted == [] and len(failures) == 1
    assert "pillow==12.0.0" in failures[0] and "13.0.0" in failures[0]


def test_vulnerability_without_a_fix_still_fails():
    failures, _ = audit.evaluate(report({"id": "PYSEC-2026-2", "fix_versions": []}), {}, TODAY)
    assert failures and "no fix released" in failures[0]


@pytest.mark.parametrize("ident", ["PYSEC-2026-1", "cve-2026-0001", "GHSA-aaaa-bbbb-cccc"])
def test_a_dated_exception_matches_by_id_or_alias_case_insensitively(ident):
    allowed, problems = audit.parse_ignore(f"{ident} | 2026-12-31 | not reachable: we never open untrusted TIFFs", TODAY)
    assert problems == []
    failures, accepted = audit.evaluate(report(VULN), allowed, TODAY)
    assert failures == [] and len(accepted) == 1


def test_an_expired_exception_fails_again():
    allowed, _ = audit.parse_ignore("PYSEC-2026-1 | 2026-11-01 | waiting for release", TODAY)
    failures, accepted = audit.evaluate(report(VULN), allowed, TODAY)
    assert accepted == [] and "expired" in failures[0]


@pytest.mark.parametrize("line", [
    "PYSEC-2026-1",                                  # no date or reason
    "PYSEC-2026-1 | 2026-12-31 |",                   # empty reason
    "PYSEC-2026-1 | soon | because",                 # bad date
    "PYSEC-2026-1 | 2027-06-01 | too far ahead",     # more than 90 days
])
def test_bad_exception_lines_are_reported_not_silently_accepted(line):
    allowed, problems = audit.parse_ignore(line, TODAY)
    assert allowed == {} and len(problems) == 1


def test_comments_and_blank_lines_are_fine_and_shipped_file_is_clean():
    allowed, problems = audit.parse_ignore((ROOT / "security" / "audit-ignore.txt").read_text(), TODAY)
    assert problems == []


def test_main_exit_codes(tmp_path, capsys):
    ignore = tmp_path / "ignore.txt"
    ignore.write_text("")
    bad, good = tmp_path / "bad.json", tmp_path / "good.json"
    bad.write_text(json.dumps(report(VULN)))
    good.write_text(json.dumps(report()))
    common = ["--ignore-file", str(ignore), "--today", TODAY.isoformat()]
    assert audit.main(["--from-json", str(good), *common]) == 0
    assert "OK" in capsys.readouterr().out
    assert audit.main(["--from-json", str(bad), *common]) == 1
    assert "VULNERABLE" in capsys.readouterr().out
    ignore.write_text("PYSEC-2026-1 | 2026-12-31 | reviewed")
    assert audit.main(["--from-json", str(bad), *common]) == 0
    ignore.write_text("garbage")
    assert audit.main(["--from-json", str(good), *common]) == 1    # a broken ignore file fails even on a clean report


def test_workflow_runs_the_audit_and_the_pin_check():
    wf = (ROOT / ".github" / "workflows" / "pytest.yml").read_text()
    assert "pip-audit" in wf and "tools/audit_deps.py" in wf and "tools/pin_requirements.py --check" in wf
    assert "schedule:" in wf   # weekly run: advisories appear without code changes


# ------------------------------------------------------------------ pins
def test_pin_tool_writes_exact_pins_that_pass_its_own_check(tmp_path):
    req, lock = tmp_path / "req.txt", tmp_path / "req.lock"
    req.write_text("Flask>=3.0,<4   # comment\n")
    assert pins.main(["--requirements", str(req), "--lock", str(lock)]) == 0
    lines = [l for l in lock.read_text().splitlines() if l and not l.startswith("#")]
    assert lines and all(re.fullmatch(r"[A-Za-z0-9._-]+==[^=<>~!\s]+", l) for l in lines)
    names = {l.split("==")[0] for l in lines}
    assert {"flask", "werkzeug", "jinja2"} <= names          # indirect packages are pinned too
    assert pins.main(["--check", "--requirements", str(req), "--lock", str(lock)]) == 0


def test_pin_check_fails_for_missing_loose_or_out_of_range(tmp_path):
    req, lock = tmp_path / "req.txt", tmp_path / "req.lock"
    req.write_text("Flask>=3.0,<4\n")
    assert pins.main(["--check", "--requirements", str(req), "--lock", str(lock)]) == 1      # no lock file
    lock.write_text("flask>=3.0\n")
    assert pins.main(["--check", "--requirements", str(req), "--lock", str(lock)]) == 1      # not ==
    lock.write_text("flask==2.0.0\n")
    assert pins.main(["--check", "--requirements", str(req), "--lock", str(lock)]) == 1      # outside the range
    lock.write_text("jinja2==3.1.6\n")
    assert pins.main(["--check", "--requirements", str(req), "--lock", str(lock)]) == 1      # Flask itself not pinned


def test_a_committed_lock_file_must_be_exact_and_inside_the_ranges():
    lock = ROOT / "requirements.lock"
    if not lock.exists():
        pytest.skip("requirements.lock is generated by `python tools/pin_requirements.py` (CI job `audit` publishes it)")
    assert pins.main(["--check", "--requirements", str(ROOT / "requirements.txt"), "--lock", str(lock)]) == 0


# ------------------------------------------------------------------ security.txt
@pytest.fixture()
def contact(app, monkeypatch):
    monkeypatch.setitem(app.config, "SECURITY_CONTACT", "security@rrfoods.example")
    monkeypatch.setitem(app.config, "SECURITY_TXT_EXPIRES", "")
    return app.test_client()


def test_security_txt_follows_rfc_9116(contact):
    r = contact.get("/.well-known/security.txt")
    assert r.status_code == 200 and r.mimetype == "text/plain" and "utf-8" in r.content_type.lower()
    body = r.get_data(as_text=True)
    assert body.endswith("\n")
    assert "Contact: mailto:security@rrfoods.example\n" in body        # a bare address becomes a mailto: URI
    assert re.search(r"^Canonical: https?://\S+/\.well-known/security\.txt$", body, re.M)
    expires = re.search(r"^Expires: (\S+)$", body, re.M).group(1)
    when = datetime.strptime(expires, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert timedelta(days=30) < when - datetime.now(timezone.utc) < timedelta(days=366)   # RFC: at most a year ahead
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_security_txt_needs_no_login_and_legacy_path_redirects(contact):
    assert contact.get("/security.txt").status_code == 301
    assert contact.get("/security.txt").headers["Location"].endswith("/.well-known/security.txt")


def test_fixed_expiry_and_https_contact_are_used_as_given(app, monkeypatch):
    monkeypatch.setitem(app.config, "SECURITY_CONTACT", "https://rrfoods.example/report")
    monkeypatch.setitem(app.config, "SECURITY_TXT_EXPIRES", "2027-03-01T00:00:00Z")
    body = app.test_client().get("/.well-known/security.txt").get_data(as_text=True)
    assert "Contact: https://rrfoods.example/report\n" in body and "Expires: 2027-03-01T00:00:00Z\n" in body


@pytest.mark.parametrize("value", ["", "   ", "javascript:alert(1)", "a@b.c\nExpires: 2099-01-01T00:00:00Z", "two words@x.com"])
def test_security_txt_is_404_rather_than_wrong(app, monkeypatch, value):
    monkeypatch.setitem(app.config, "SECURITY_CONTACT", value)
    assert app.test_client().get("/.well-known/security.txt").status_code == 404


# ------------------------------------------------------------------ account lockout
def attempt(client, email, password, url="/login"):
    return post(client, url, {"email": email, "password": password}, page=url)


def user_row(session, email="user@test.com"):
    session.expire_all()
    return session.scalar(select(User).where(User.email == email))


@pytest.fixture()
def customer(session):
    return make_user(session, "user")


def test_five_wrong_passwords_lock_the_account_even_for_the_right_password(app, session, customer):
    c = app.test_client()
    for _ in range(5):
        r = attempt(c, "user@test.com", "wrong-password")
        assert r.status_code == 401 and "Incorrect email or password." in r.get_data(as_text=True)
    r = attempt(c, "user@test.com", PW)                      # the correct password is refused while locked
    assert r.status_code == 429 and "Too many attempts" in r.get_data(as_text=True)
    assert "Set-Cookie" not in r.headers or "user_id" not in r.headers.get("Set-Cookie", "")
    row = user_row(session)
    assert row.locked_until and row.locked_until > utcnow()
    assert session.scalar(select(AuditLog).where(AuditLog.action == "auth.locked", AuditLog.entity_id == str(row.id)))
    assert c.get("/account").status_code == 302              # still signed out


def test_lock_lasts_about_the_configured_minutes(app, session, customer):
    c = app.test_client()
    for _ in range(5):
        attempt(c, "user@test.com", "nope")
    left = user_row(session).locked_until - utcnow()
    assert timedelta(minutes=app.config["LOCKOUT_MINUTES"] - 1) < left <= timedelta(minutes=app.config["LOCKOUT_MINUTES"])


def test_signing_in_works_again_after_the_lock_expires(app, session, customer):
    c = app.test_client()
    for _ in range(5):
        attempt(c, "user@test.com", "nope")
    assert attempt(c, "user@test.com", PW).status_code == 429
    past = utcnow() - timedelta(minutes=1)
    session.execute(update(User).values(locked_until=past))
    session.execute(update(LoginLockout).values(locked_until=past))
    session.commit()
    assert attempt(c, "user@test.com", PW).status_code == 302


def test_unknown_email_is_locked_and_answers_exactly_like_a_real_one(app, session, customer):
    c = app.test_client()
    first_real = attempt(c, "user@test.com", "nope").get_data(as_text=True)
    first_fake = attempt(c, "nobody@test.com", "nope").get_data(as_text=True)
    assert "Incorrect email or password." in first_real and "Incorrect email or password." in first_fake
    for _ in range(4):
        attempt(c, "nobody@test.com", "nope")
    r = attempt(c, "nobody@test.com", "nope")
    assert r.status_code == 429 and "Too many attempts" in r.get_data(as_text=True)   # same lock message as a real account


def test_a_successful_sign_in_resets_the_failed_counter(app, session, customer):
    c = app.test_client()
    for _ in range(4):
        attempt(c, "user@test.com", "nope")
    assert attempt(c, "user@test.com", PW).status_code == 302
    c2 = app.test_client()
    for _ in range(4):                                          # four more wrong ones: 4 + 4 would have locked it before 5.7
        assert attempt(c2, "user@test.com", "nope").status_code == 401
    assert attempt(c2, "user@test.com", PW).status_code == 302


def test_one_address_failing_for_many_accounts_is_locked_by_ip(app, session, customer):
    c = app.test_client()
    for i in range(app.config["LOGIN_IP_MAX_FAILED"]):
        assert attempt(c, f"ghost{i}@test.com", "nope").status_code == 401   # one failure each: no account lock yet
    r = attempt(c, "user@test.com", PW)
    assert r.status_code == 429 and "Too many attempts" in r.get_data(as_text=True)


def test_lockout_rows_hold_hashes_not_the_email_or_ip(app, session, customer):
    attempt(app.test_client(), "user@test.com", "nope")
    rows = session.scalars(select(LoginLockout)).all()
    assert {r.scope for r in rows} == {"account", "ip"}
    for r in rows:
        assert re.fullmatch(r"[0-9a-f]{64}", r.subject_hash)
        assert "user@test.com" not in r.subject_hash and "127.0.0.1" not in r.subject_hash


def test_right_password_on_the_wrong_portal_does_not_count_towards_a_lock(app, session, customer):
    c = app.test_client()
    for _ in range(app.config["MAX_FAILED_LOGINS"] + 2):
        assert attempt(c, "user@test.com", PW, url="/admin/login").status_code == 401
    assert attempt(c, "user@test.com", PW).status_code == 302
