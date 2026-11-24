"""Create account with email verification: the account exists only after the emailed 6 digit code is entered."""
import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.extensions import limiter
from app.models import AuditLog, EmailOtp, User
from app.models.base import utcnow
from app.services.mailer import MailUnavailable
from tests.helpers import make_user, post, token

FORM = {"name": "Asha Rao", "email": "asha@example.com", "phone": "9876543210", "password": "Sup3rSecret!x", "confirm": "Sup3rSecret!x"}


@pytest.fixture(autouse=True)
def _no_flask_limiter(app):
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def sent(monkeypatch):
    box = []
    import app.auth.otp as otp
    monkeypatch.setattr(otp, "send_now", lambda to, subject, text, html=None: box.append((to, subject, text, html)))
    return box


def _code(sent):
    return re.search(r"code is (\d{6})", sent[-1][2]).group(1)


def _start(client, **over):
    return post(client, "/register", {**FORM, **over}, page="/register")


def _verify(client, code):
    return post(client, "/register/verify", {"code": code}, page="/register/verify")


def _user(session, email="asha@example.com"):
    return session.scalar(select(User).where(User.email == email))


def _wrong(code):
    return "000000" if code != "000000" else "111111"


# ---------------------------------------------------------------- step 1
def test_form_does_not_create_the_account_it_emails_a_code(client, session, sent):
    r = _start(client)
    assert r.status_code == 302 and r.headers["Location"] == "/register/verify"
    assert _user(session) is None                                              # nothing yet
    assert len(sent) == 1 and sent[0][0] == "asha@example.com"
    to, subject, text, html = sent[0]
    assert _code(sent) in subject and "verify your email" in text and "valid for 5 minutes" in text and "Do not share it" in text and html
    row = session.scalar(select(EmailOtp))
    assert row.otp_hash != _code(sent) and len(row.otp_hash) == 64 and not row.is_used   # only a hash is stored
    page = client.get("/register/verify").get_data(as_text=True)
    assert "asha@example.com" in page and 'name="code"' in page and "Resend code" in page and "autocomplete=\"one-time-code\"" in page


def test_register_page_explains_the_two_steps(client):
    html = client.get("/register").get_data(as_text=True)
    assert "Send verification code" in html and "6 digit code" in html


def test_invalid_form_sends_no_email(client, session, sent):
    r = _start(client, password="short")
    assert r.status_code == 422 and sent == [] and session.scalar(select(EmailOtp)) is None


def test_existing_email_is_refused_and_gets_no_code(client, session, sent):
    make_user(session, "user", "asha@example.com")
    r = _start(client)
    assert r.status_code == 422 and "already exists" in r.get_data(as_text=True) and sent == []


def test_password_is_hashed_in_the_session_never_kept_as_typed(client, session, sent):
    _start(client)
    with client.session_transaction() as s:
        pending = s["signup"]
    assert pending["pw"].startswith("$argon2") and FORM["password"] not in str(pending)


def test_email_outage_shows_a_message_and_keeps_nothing(client, session, monkeypatch):
    import app.auth.otp as otp

    def boom(*a, **k):
        raise MailUnavailable("off")
    monkeypatch.setattr(otp, "send_now", boom)
    r = _start(client)
    assert r.status_code == 503 and "cannot send verification emails" in r.get_data(as_text=True)
    assert _user(session) is None and session.scalar(select(EmailOtp)) is None      # a failed send must not use up the cooldown
    with client.session_transaction() as s:
        assert "signup" not in s


# ---------------------------------------------------------------- step 2
def test_right_code_creates_a_verified_customer_and_signs_in(client, session, sent):
    _start(client, **{"role": "admin"})
    r = _verify(client, _code(sent))
    assert r.status_code == 302 and r.headers["Location"] == "/account"
    u = _user(session)
    assert u.role == "user" and u.email_verified_at is not None and u.phone == "9876543210" and u.name == "Asha Rao"
    assert u.password_hash.startswith("$argon2") and u.referral_code.startswith("RR")
    assert client.get("/account").status_code == 200 and client.get("/admin/").status_code == 403
    assert session.scalar(select(AuditLog).where(AuditLog.action == "auth.register")).after == {"via": "signup_otp"}
    with client.session_transaction() as s:
        assert "signup" not in s                                            # pending sign-up is gone
    assert client.get("/register/verify").status_code == 302                # signed in: nothing to verify


def test_the_chosen_password_works_for_a_later_sign_in(client, session, sent, app):
    _start(client)
    _verify(client, _code(sent))
    c2 = app.test_client()
    r = c2.post("/login", data={"email": "asha@example.com", "password": FORM["password"], "csrf_token": token(c2, "/login")})
    assert r.status_code == 302


def test_wrong_code_creates_nothing_and_five_wrong_guesses_lock_it(client, session, sent):
    _start(client)
    good = _code(sent)
    for _ in range(4):
        r = _verify(client, _wrong(good))
        assert r.status_code == 400 and "incorrect or has expired" in r.get_data(as_text=True)
    r = _verify(client, _wrong(good))
    assert "Too many wrong attempts" in r.get_data(as_text=True) and "ask for a new code" in r.get_data(as_text=True)
    assert _verify(client, good).status_code == 400                         # even the right code is dead now
    assert _user(session) is None


def test_expired_code_is_refused(client, session, sent):
    _start(client)
    row = session.scalar(select(EmailOtp))
    row.expires_at = utcnow() - timedelta(seconds=1)
    session.commit()
    r = _verify(client, _code(sent))
    assert r.status_code == 400 and "Please ask for a new code" in r.get_data(as_text=True) and _user(session) is None


@pytest.mark.parametrize("code", ["", "12345", "abcdef", "1234567"])
def test_malformed_code_is_a_422(client, session, sent, code):
    _start(client)
    assert _verify(client, code).status_code == 422 and _user(session) is None


def test_code_is_single_use(client, session, sent, app):
    _start(client)
    code = _code(sent)
    with client.session_transaction() as s:
        saved = dict(s)                                              # what a second device holding the same half-finished sign-up would have
    assert _verify(client, code).status_code == 302
    assert session.scalar(select(EmailOtp)).is_used
    replay = app.test_client()
    with replay.session_transaction() as s:
        s.update(saved)
    r = _verify(replay, code)
    assert r.status_code == 400 and "incorrect or has expired" in r.get_data(as_text=True)
    assert len(session.scalars(select(User).where(User.email == "asha@example.com")).all()) == 1


def test_verify_without_a_started_signup_goes_back_to_the_form(client):
    assert client.get("/register/verify").headers["Location"] == "/register"
    r = post(client, "/register/verify", {"code": "123456"}, page="/register")
    assert r.status_code == 302 and r.headers["Location"] == "/register"


def test_half_finished_signup_expires(client, session, sent):
    _start(client)
    with client.session_transaction() as s:
        s["signup"] = {**s["signup"], "t": (utcnow() - timedelta(hours=2)).timestamp()}     # reassign: Flask misses in-place edits
    assert client.get("/register/verify").headers["Location"] == "/register"


def test_change_email_returns_to_the_prefilled_form(client, session, sent):
    _start(client)
    html = client.get("/register").get_data(as_text=True)
    assert 'value="asha@example.com"' in html and 'value="Asha Rao"' in html and FORM["password"] not in html


# ---------------------------------------------------------------- the two kinds of codes never mix
def test_a_signup_code_cannot_sign_in_through_the_login_route(client, session, sent):
    _start(client)
    c2 = client.application.test_client()
    r = c2.post("/login/otp/verify", json={"email": "asha@example.com", "code": _code(sent)}, headers={"X-CSRFToken": token(c2, "/login")})
    assert r.status_code == 400 and _user(session) is None


def test_a_login_code_cannot_finish_a_signup(client, session, sent, app, monkeypatch):
    monkeypatch.setitem(app.config, "OTP_RESEND_SECONDS", 0)
    c2 = app.test_client()
    c2.post("/login/otp/send", json={"email": "asha@example.com"}, headers={"X-CSRFToken": token(c2, "/login")})
    login_code = _code(sent)
    _start(client)
    signup_code = _code(sent)
    r = _verify(client, login_code if login_code != signup_code else _wrong(signup_code))
    assert r.status_code == 400 and _user(session) is None


# ---------------------------------------------------------------- resend and limits
def test_resend_is_blocked_during_the_cooldown(client, session, sent):
    _start(client)
    r = post(client, "/register/resend", {}, page="/register/verify")
    assert r.status_code == 429 and "Please wait" in r.get_data(as_text=True) and len(sent) == 1


def test_resend_sends_a_new_code_and_the_old_one_stops_working(client, session, sent, app, monkeypatch):
    monkeypatch.setitem(app.config, "OTP_RESEND_SECONDS", 0)
    _start(client)
    old = _code(sent)
    r = post(client, "/register/resend", {}, page="/register/verify")
    assert r.status_code == 302 and len(sent) == 2
    new = _code(sent)
    if new == old:                                   # 1 in a million: pick the stale-code check off
        pytest.skip("same random code twice")
    assert _verify(client, old).status_code == 400
    assert _verify(client, new).status_code == 302 and _user(session) is not None


def test_resubmitting_the_form_right_away_keeps_the_code_already_sent(client, session, sent):
    _start(client)
    r = _start(client)                               # back button + submit again, inside the cooldown
    assert r.status_code == 302 and r.headers["Location"] == "/register/verify" and len(sent) == 1
    assert _verify(client, _code(sent)).status_code == 302


def test_hourly_cap_stops_code_requests_for_one_address(client, session, sent, app, monkeypatch):
    monkeypatch.setitem(app.config, "OTP_RESEND_SECONDS", 0)
    assert _start(client).status_code == 302
    for _ in range(app.config["OTP_MAX_PER_EMAIL_HOUR"] - 1):
        assert post(client, "/register/resend", {}, page="/register/verify").status_code == 302
    assert len(sent) == app.config["OTP_MAX_PER_EMAIL_HOUR"]
    r = post(client, "/register/resend", {}, page="/register/verify")                # one more than the cap
    assert r.status_code == 429 and "Too many code requests" in r.get_data(as_text=True) and len(sent) == app.config["OTP_MAX_PER_EMAIL_HOUR"]


def test_address_taken_between_the_steps_does_not_make_a_second_account(client, session, sent):
    _start(client)
    make_user(session, "user", "asha@example.com")                          # someone else finished first
    r = _verify(client, _code(sent))
    assert r.status_code == 302 and r.headers["Location"] == "/login"
    assert len(session.scalars(select(User).where(User.email == "asha@example.com")).all()) == 1


def test_verify_and_resend_need_a_csrf_token(client, session, sent):
    _start(client)
    assert client.post("/register/verify", data={"code": _code(sent)}).status_code == 400
    assert client.post("/register/resend", data={}).status_code == 400
