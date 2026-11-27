"""Change password when the current password is forgotten: a 6 digit code is emailed to the signed-in account's own address."""
import re

import pytest

from app.security import verify_password

from tests.helpers import PW, make_user, post, sign_in, token

NEW = "Br4ndNew!Pass9"
PAGES = {"user": "/account/password", "admin": "/admin/password", "owner": "/owner/password"}


def _capture(monkeypatch):
    sent = []
    import app.auth.otp as otp
    monkeypatch.setattr(otp, "send_now", lambda to, subject, text, html=None: sent.append((to, subject, text, html)))
    return sent


def _code(sent):
    return re.search(r"code is (\d{6})", sent[-1][2]).group(1)


def test_page_offers_the_email_code_option(client, session):
    make_user(session, "user")
    sign_in(client, "user")
    html = client.get("/account/password").get_data(as_text=True)
    assert "Forgot your current password" in html
    html = client.get("/account/password?forgot=1").get_data(as_text=True)
    assert "Send code to my email" in html
    assert "us**@test.com" in html and "user@test.com" not in html           # masked address, never the full one


@pytest.mark.parametrize("role", ["user", "admin", "owner"])
def test_forgotten_password_changed_with_emailed_code(client, session, monkeypatch, role):
    u = make_user(session, role)
    sent = _capture(monkeypatch)
    sign_in(client, role)
    url = PAGES[role]
    r = post(client, url, {"action": "send_code"}, page=url)
    assert r.status_code == 200 and "6 digit code" in r.get_data(as_text=True)
    assert sent and sent[-1][0] == f"{role}@test.com"                       # sent to the account's own address only
    r = post(client, url, {"action": "change_with_code", "code": _code(sent), "new": NEW, "confirm": NEW}, page=url)
    assert r.status_code == 302
    session.refresh(u)
    assert verify_password(u.password_hash, NEW)


def test_wrong_code_does_not_change_password(client, session, monkeypatch):
    u = make_user(session, "user")
    sent = _capture(monkeypatch)
    sign_in(client, "user")
    post(client, "/account/password", {"action": "send_code"})
    good = _code(sent)
    bad = "000000" if good != "000000" else "111111"
    r = post(client, "/account/password", {"action": "change_with_code", "code": bad, "new": NEW, "confirm": NEW})
    assert r.status_code == 422 and "incorrect or has expired" in r.get_data(as_text=True)
    session.refresh(u)
    assert verify_password(u.password_hash, PW)


def test_code_is_single_use_and_checks_password_rules_first(client, session, monkeypatch):
    make_user(session, "user")
    sent = _capture(monkeypatch)
    sign_in(client, "user")
    post(client, "/account/password", {"action": "send_code"})
    code = _code(sent)
    r = post(client, "/account/password", {"action": "change_with_code", "code": code, "new": "weak", "confirm": "weak"})
    assert r.status_code == 422                                              # weak password: code NOT used up
    r = post(client, "/account/password", {"action": "change_with_code", "code": code, "new": NEW, "confirm": NEW})
    assert r.status_code == 302
    r = post(client, "/account/password", {"action": "change_with_code", "code": code, "new": NEW + "x", "confirm": NEW + "x"})
    assert r.status_code == 422                                              # used code is dead


def test_password_change_code_cannot_sign_anyone_in(client, session, monkeypatch):
    make_user(session, "user", "c@test.com")
    sent = _capture(monkeypatch)
    client.post("/login", data={"email": "c@test.com", "password": PW, "csrf_token": token(client, "/login")})
    post(client, "/account/password", {"action": "send_code"})
    code = _code(sent)
    other = client.application.test_client()
    r = other.post("/login/otp/verify", json={"email": "c@test.com", "code": code}, headers={"X-CSRFToken": token(other, "/login")})
    assert r.status_code == 400 and not r.json["ok"]                         # purpose is mixed into the code's hash
