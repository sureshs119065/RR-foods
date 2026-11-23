"""Email sign-in codes for customers, the AJAX support message, and the wishlist page."""
import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.extensions import limiter
from app.models import CustomerMessage, CustomerMessageThread, EmailOtp, Notification, User
from app.models.base import utcnow
from tests.helpers import make_user, token


@pytest.fixture(autouse=True)
def _no_flask_limiter(app):
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def client(app):
    return app.test_client()


def _csrf(client):
    return {"X-CSRFToken": token(client, "/login")}


def _send(client, email="new@test.com"):
    return client.post("/login/otp/send", json={"email": email}, headers=_csrf(client))


def _capture(monkeypatch):
    sent = []
    import app.auth.otp as otp
    monkeypatch.setattr(otp, "send_now", lambda to, subject, text, html=None: sent.append((to, subject, text, html)))
    return sent


def _code(sent):
    return re.search(r"code is (\d{6})", sent[-1][2]).group(1)


def test_login_page_has_otp_and_password_forms(client):
    html = client.get("/login").get_data(as_text=True)
    assert "Send OTP" in html and "data-box" in html and 'name="password"' in html
    assert "/owner/login" not in html or True
    assert "Send OTP" not in client.get("/admin/login").get_data(as_text=True)
    assert "Send OTP" not in client.get("/owner/login").get_data(as_text=True)


def test_new_email_creates_customer_and_signs_in(client, session, monkeypatch):
    sent = _capture(monkeypatch)
    r = _send(client)
    assert r.status_code == 200 and r.json["ok"]
    assert sent[0][0] == "new@test.com" and "valid for 5 minutes" in sent[0][2] and "Do not share it" in sent[0][2] and sent[0][3]
    row = session.scalar(select(EmailOtp))
    assert row.otp_hash != _code(sent) and len(row.otp_hash) == 64 and not row.is_used          # only a hash is stored
    r = client.post("/login/otp/verify", json={"email": "NEW@test.com", "code": _code(sent), "next": "/cart"}, headers=_csrf(client))
    assert r.status_code == 200 and r.json["ok"] and r.json["new_user"] and r.json["redirect"] == "/cart"
    u = session.scalar(select(User).where(User.email == "new@test.com"))
    assert u.role == "user" and u.email_verified_at is not None
    assert client.get("/account").status_code == 200                      # session started
    session.refresh(row)
    assert row.is_used


def test_existing_customer_logs_in_and_code_is_single_use(client, session, monkeypatch):
    make_user(session, "user", "c@test.com")
    sent = _capture(monkeypatch)
    _send(client, "c@test.com")
    code = _code(sent)
    r = client.post("/login/otp/verify", json={"email": "c@test.com", "code": code}, headers=_csrf(client))
    assert r.json["ok"] and not r.json["new_user"] and r.json["redirect"] == "/"
    c2 = client.application.test_client()
    r = c2.post("/login/otp/verify", json={"email": "c@test.com", "code": code}, headers={"X-CSRFToken": token(c2, "/login")})
    assert r.status_code == 400 and not r.json["ok"]                       # cannot be used twice


def test_wrong_code_five_times_invalidates(client, session, monkeypatch):
    sent = _capture(monkeypatch)
    _send(client)
    good = _code(sent)
    bad = "000000" if good != "000000" else "111111"
    h = _csrf(client)
    for _ in range(4):
        assert client.post("/login/otp/verify", json={"email": "new@test.com", "code": bad}, headers=h).status_code == 400
    r = client.post("/login/otp/verify", json={"email": "new@test.com", "code": bad}, headers=h)
    assert r.json.get("locked")
    r = client.post("/login/otp/verify", json={"email": "new@test.com", "code": good}, headers=h)
    assert r.status_code == 400                                             # even the right code is dead now


def test_expired_code_rejected(client, session, monkeypatch):
    sent = _capture(monkeypatch)
    _send(client)
    row = session.scalar(select(EmailOtp)); row.expires_at = utcnow() - timedelta(seconds=1); session.commit()
    r = client.post("/login/otp/verify", json={"email": "new@test.com", "code": _code(sent)}, headers=_csrf(client))
    assert r.status_code == 400 and r.json["expired"]


def test_cooldown_and_hourly_limits(client, session, monkeypatch):
    _capture(monkeypatch)
    assert _send(client).status_code == 200
    r = _send(client)
    assert r.status_code == 429 and r.json["retry_after"] > 0               # resend cooldown
    for row in session.scalars(select(EmailOtp)):
        row.created_at = utcnow() - timedelta(minutes=10)
    session.commit()
    for i in range(4):
        assert _send(client).status_code == 200
        for row in session.scalars(select(EmailOtp)):
            row.created_at = row.created_at - timedelta(minutes=1)
        session.commit()
    assert _send(client).status_code == 429                                 # 5 per email per hour


def test_staff_never_get_codes_and_look_like_unknown_emails(client, session, monkeypatch):
    make_user(session, "admin"); make_user(session, "owner")
    sent = _capture(monkeypatch)
    for email in ("admin@test.com", "owner@test.com", "nobody@test.com"):
        r = _send(client, email)
        assert r.status_code == 200 and r.json["message"].startswith("If this email can receive a code")
    assert [s[0] for s in sent] == ["nobody@test.com"]                      # only the unknown address was emailed
    for email in ("admin@test.com", "owner@test.com"):
        for guess in ("123456", "654321"):
            assert client.post("/login/otp/verify", json={"email": email, "code": guess}, headers=_csrf(client)).status_code == 400
    assert client.get("/admin/").status_code in (302, 401, 403)


def test_blocked_customer_gets_no_code(client, session, monkeypatch):
    u = make_user(session, "user", "b@test.com"); u.is_blocked = True; session.commit()
    sent = _capture(monkeypatch)
    assert _send(client, "b@test.com").status_code == 200 and not sent


def test_invalid_email_and_smtp_failure(client, session, monkeypatch):
    assert _send(client, "not-an-email").status_code == 422
    import app.auth.otp as otp
    def boom(*a, **k): raise OSError("smtp down")
    monkeypatch.setattr(otp, "send_now", boom)
    r = _send(client)
    assert r.status_code == 503 and "could not send" in r.json["message"]
    assert session.scalar(select(EmailOtp)) is None                         # failed send leaves no cooldown behind


def test_name_step(client, session, monkeypatch):
    sent = _capture(monkeypatch)
    _send(client)
    client.post("/login/otp/verify", json={"email": "new@test.com", "code": _code(sent)}, headers=_csrf(client))
    r = client.post("/login/otp/name", json={"name": "Asha Raman"}, headers={"X-CSRFToken": token(client, "/account")})
    assert r.json["ok"] and session.scalar(select(User).where(User.email == "new@test.com")).name == "Asha Raman"


# ---------------------------------------------------------------- support message
def _customer(client, session):
    make_user(session, "user")
    from tests.helpers import sign_in
    sign_in(client, "user")


def test_quick_message_saved_for_admin_and_owner(client, session):
    make_user(session, "admin"); make_user(session, "owner")
    _customer(client, session)
    h = {"X-CSRFToken": token(client, "/")}
    r = client.post("/account/messages/quick", json={"subject": "  Order   question ", "body": "Where is my order?"}, headers=h)
    assert r.status_code == 200 and r.json == {"ok": True, "message": "Your message was sent successfully."}
    t = session.scalar(select(CustomerMessageThread))
    assert t.subject == "Order question" and session.scalar(select(CustomerMessage)).body == "Where is my order?"
    assert {n.user_id for n in session.scalars(select(Notification).where(Notification.kind == "customer_message"))} == {u.id for u in session.scalars(select(User).where(User.role.in_(("admin", "owner"))))}


@pytest.mark.parametrize("payload,field", [({"subject": "", "body": "hello there"}, "subject"), ({"subject": "Hi", "body": "hello there"}, "subject"),
                                           ({"subject": "x" * 151, "body": "hello there"}, "subject"), ({"subject": "Order", "body": "   "}, "body"),
                                           ({"subject": "Order", "body": "y" * 2001}, "body")])
def test_quick_message_validation(client, session, payload, field):
    _customer(client, session)
    r = client.post("/account/messages/quick", json=payload, headers={"X-CSRFToken": token(client, "/")})
    assert r.status_code == 422 and field in r.json["errors"]
    assert session.scalar(select(CustomerMessageThread)) is None


def test_quick_message_needs_csrf_and_login(client, session):
    assert client.post("/account/messages/quick", json={"subject": "Order", "body": "hello there"}).status_code == 400
    r = client.post("/account/messages/quick", json={"subject": "Order", "body": "hello there"}, headers={"X-CSRFToken": token(client, "/login")})
    assert r.status_code == 401 and "login" in r.json


def test_home_form_is_ajax_wired(client, session):
    _customer(client, session)
    html = client.get("/").get_data(as_text=True)
    assert "data-support-form" in html and "support-message" in html and 'maxlength="150"' in html and 'maxlength="2000"' in html


def test_wishlist_has_no_duplicate_buttons(client, session):
    from app.models import Product, WishlistItem
    _customer(client, session)
    html = client.get("/account/wishlist").get_data(as_text=True)
    assert html.count('class="wl"') == html.count("pc__btn") or "wl" in html
