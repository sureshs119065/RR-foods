"""Login page: one sign-in method visible at a time, create-account link, password eye, HTTPS email modes."""
import re

import pytest


@pytest.fixture()
def client(app, session):
    return app.test_client()


def test_login_shows_password_form_first_with_email_otp_switch(client):
    html = client.get("/login").get_data(as_text=True)
    assert "<details" not in html
    assert 'data-switch="code"' in html and 'data-switch="password"' in html
    assert re.search(r'data-panel="password"(?![^>]*hidden)', html)
    assert re.search(r'data-panel="code"[^>]*hidden', html)
    assert "Send OTP" in html and "Continue with Email OTP" in html and "Welcome Back!" in html
    assert 'href="/register"' in html and "Register Here" in html
    assert "auth-ui.js" in html


def test_wrong_password_opens_the_password_tab(client, session):
    from helpers import token
    r = client.post("/login", data={"email": "nobody@example.com", "password": "wrong-pass-1", "csrf_token": token(client, "/login")})
    html = r.get_data(as_text=True)
    assert r.status_code in (401, 429)
    assert re.search(r'data-panel="password"(?![^>]*hidden)', html)
    assert re.search(r'data-panel="code"[^>]*hidden', html)


@pytest.mark.parametrize("url", ["/register", "/forgot", "/admin/login", "/owner/login"])
def test_other_auth_pages_load_the_eye_script(client, url):
    assert "auth-ui.js" in client.get(url).get_data(as_text=True)


def test_brevo_mode_posts_over_https(app, monkeypatch):
    import app.services.mailer as mailer
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    def fake_urlopen(req, timeout=0):
        seen["url"], seen["body"], seen["key"] = req.full_url, req.data, req.headers.get("Api-key")
        return Resp()

    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    with app.app_context():
        app.config.update(MAIL_MODE="brevo", BREVO_API_KEY="k123", MAIL_FROM="RR FOODS <shop@example.com>")
        try:
            mailer.send_now("a@b.co", "123456 is your code", "code 123456", "<b>123456</b>")
        finally:
            app.config.update(MAIL_MODE="console", BREVO_API_KEY="")
    assert seen["url"] == "https://api.brevo.com/v3/smtp/email" and seen["key"] == "k123"
    assert b"shop@example.com" in seen["body"] and b"a@b.co" in seen["body"]


def test_api_mode_without_key_is_unavailable(app):
    import app.services.mailer as mailer
    with app.app_context():
        app.config.update(MAIL_MODE="brevo", BREVO_API_KEY="", MAIL_FROM="x <x@example.com>")
        try:
            with pytest.raises(mailer.MailUnavailable):
                mailer.send_now("a@b.co", "s", "t")
        finally:
            app.config.update(MAIL_MODE="console")
