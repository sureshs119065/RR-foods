import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, LoginLockout, User
from app.models.base import utcnow
from app.security import hash_password

PW = "Sup3rSecret!"


@pytest.fixture()
def users(session):
    made = {}
    for role in ("user", "owner", "admin"):
        u = User(email=f"{role}@test.com", name=role.title(), role=role, password_hash=hash_password(PW))
        session.add(u)
        made[role] = u
    session.commit()
    return made


@pytest.fixture()
def client(app):
    return app.test_client()


def token(client, url="/login"):
    html = client.get(url).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def post(client, url, data, page=None):
    data = dict(data)
    data["csrf_token"] = token(client, page or url)
    return client.post(url, data=data)


def sign_in(client, role, portal=None, password=PW):
    url = {"user": "/login", "owner": "/owner/login", "admin": "/admin/login"}[portal or role]
    return post(client, url, {"email": f"{role}@test.com", "password": password})


# ---------------- three separate logins ----------------
@pytest.mark.parametrize("role,home", [("user", "/account"), ("owner", "/owner/"), ("admin", "/admin/")])
def test_each_role_signs_in_on_its_own_portal(client, users, role, home):
    r = sign_in(client, role)
    assert r.status_code == 302 and r.headers["Location"] == home
    assert client.get(home).status_code == 200


@pytest.mark.parametrize("role,wrong_portal", [
    ("user", "owner"), ("user", "admin"), ("owner", "user"), ("owner", "admin"), ("admin", "user"), ("admin", "owner"),
])
def test_correct_password_on_the_wrong_portal_is_refused_with_a_generic_message(client, users, role, wrong_portal):
    r = sign_in(client, role, portal=wrong_portal)
    assert r.status_code == 401
    body = r.get_data(as_text=True)
    assert "Incorrect email or password." in body
    for leak in ("owner account", "admin account", "customer account", "wrong portal", "not an owner", "not an admin"):
        assert leak not in body.lower()  # the page does not reveal the account's real role
    assert client.get("/account").status_code == 302  # still signed out


def test_unknown_email_and_wrong_password_look_identical(client, users):
    a = post(client, "/login", {"email": "nobody@test.com", "password": "whatever1"}).get_data(as_text=True)
    b = post(client, "/login", {"email": "user@test.com", "password": "wrong-pass1"}).get_data(as_text=True)
    strip = lambda h: re.sub(r'value="[^"]*"', "", h)
    assert "Incorrect email or password." in a and strip(a) == strip(b)


def test_email_is_case_insensitive(client, users):
    r = post(client, "/login", {"email": "  USER@Test.COM ", "password": PW})
    assert r.status_code == 302


# ---------------- RBAC ----------------
def test_anonymous_visitors_are_sent_to_the_right_login(client, users):
    assert client.get("/account").headers["Location"].startswith("/login")
    assert client.get("/owner/").headers["Location"].startswith("/owner/login")
    assert client.get("/admin/").headers["Location"].startswith("/admin/login")


@pytest.mark.parametrize("role,allowed,denied", [
    ("user", ["/account"], ["/owner/", "/admin/", "/owner/password", "/admin/password"]),
    ("owner", ["/owner/", "/owner/password"], ["/admin/", "/admin/password"]),
    ("admin", ["/admin/", "/admin/password"], ["/owner/", "/owner/password"]),
])
def test_role_access_matrix(client, users, role, allowed, denied):
    sign_in(client, role)
    for url in allowed:
        assert client.get(url).status_code == 200, url
    for url in denied:
        assert client.get(url).status_code == 403, url


def test_every_owner_and_admin_route_is_protected(app, client, users):
    """Walks the URL map, so a route added in a later step cannot be forgotten."""
    checked = 0
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith(("/admin", "/owner")) or rule.endpoint in ("auth.admin_login", "auth.owner_login"):
            continue
        path = re.sub(r"<(?:int:)?[a-z_]+>", "1", rule.rule)  # fill in ids so the real route is hit, not a 404
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            r = client.open(path, method=method)
            assert r.status_code in (302, 400), f"{method} {path} -> {r.status_code}"  # 400 = CSRF refusal on POST
            checked += 1
    assert checked >= 40  # all the Step 4 admin routes are covered too


def test_staff_cannot_use_customer_account_page(client, users):
    sign_in(client, "admin")
    assert client.get("/account").headers["Location"] == "/admin/"


# ---------------- CSRF ----------------
def test_post_without_csrf_token_is_rejected(client, users):
    r = client.post("/login", data={"email": "user@test.com", "password": PW})
    assert r.status_code == 400
    assert client.get("/account").status_code == 302


def test_logout_requires_post_and_csrf(client, users):
    sign_in(client, "user")
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 400
    assert client.get("/account").status_code == 200
    r = post(client, "/logout", {}, page="/account")
    assert r.status_code == 302
    assert client.get("/account").status_code == 302


# ---------------- sessions ----------------
def test_login_creates_a_fresh_session(client, users):
    client.get("/login")
    with client.session_transaction() as s:
        s["planted"] = "attacker-value"
    sign_in(client, "user")
    with client.session_transaction() as s:
        assert "planted" not in s and s["uid"] == users["user"].id


def test_blocking_an_account_signs_it_out_immediately(client, users, session):
    sign_in(client, "user")
    assert client.get("/account").status_code == 200
    users["user"].is_blocked = True
    session.commit()
    assert client.get("/account").status_code == 302


def test_blocked_account_cannot_sign_in(client, users, session):
    users["user"].is_blocked = True
    session.commit()
    r = sign_in(client, "user")
    assert r.status_code == 401 and "blocked" in r.get_data(as_text=True)


def test_staff_sessions_expire_when_idle_but_customers_do_not(client, users, app):
    for role in ("admin", "user"):
        sign_in(client, role)
        with client.session_transaction() as s:
            s["seen"] = (utcnow() - timedelta(minutes=app.config["STAFF_IDLE_MINUTES"] + 5)).timestamp()
        home = "/admin/" if role == "admin" else "/account"
        expect = 302 if role == "admin" else 200
        assert client.get(home).status_code == expect, role
        client.post("/logout", data={"csrf_token": "x"})
        with client.session_transaction() as s:
            s.clear()


def test_changing_password_signs_out_other_devices(users, app):
    a, b = app.test_client(), app.test_client()
    sign_in(a, "user")
    sign_in(b, "user")
    r = post(a, "/account/password", {"current": PW, "new": "N3wPassword!", "confirm": "N3wPassword!"})
    assert r.status_code == 302
    assert a.get("/account").status_code == 200  # this device stays signed in
    assert b.get("/account").status_code == 302  # the other one is signed out


# ---------------- lockout, rate limit, redirects ----------------
def test_account_locks_after_five_wrong_passwords_then_recovers(client, users, session, app):
    for _ in range(5):
        assert sign_in(client, "user", password="wrong-pass1").status_code == 401
    r = sign_in(client, "user")  # correct password, but locked
    assert r.status_code == 429 and "Too many attempts" in r.get_data(as_text=True)
    session.expire_all()
    u = session.scalar(select(User).where(User.email == "user@test.com"))
    u.locked_until = utcnow() - timedelta(seconds=1)  # lock time passes (the per-account and per-IP lockout rows too)
    for row in session.scalars(select(LoginLockout)).all():
        row.locked_until = utcnow() - timedelta(seconds=1)
    session.commit()
    assert sign_in(client, "user").status_code == 302
    session.expire_all()
    assert session.scalar(select(User).where(User.email == "user@test.com")).failed_login_count == 0


def test_right_password_on_wrong_portal_does_not_count_toward_lockout(client, users, session):
    for _ in range(8):
        sign_in(client, "user", portal="admin")
    assert sign_in(client, "user").status_code == 302


def test_login_rate_limit_per_ip(client, users, app):
    app.config["LOGIN_RATE_LIMIT"] = "3 per minute"
    try:
        codes = [sign_in(client, "user", password="wrong-pass1").status_code for _ in range(5)]
        assert codes[:3] == [401, 401, 401] and 429 in codes[3:]
    finally:
        app.config["LOGIN_RATE_LIMIT"] = "1000 per minute"


@pytest.mark.parametrize("nxt,expected", [
    ("/account/password", "/account/password"),
    ("https://evil.example/steal", "/account"),
    ("//evil.example", "/account"),
    ("/\\evil.example", "/account"),
    ("javascript:alert(1)", "/account"),
    ("/owner/", "/account"),
    ("/admin/password", "/account"),
])
def test_next_parameter_cannot_redirect_off_site(client, users, nxt, expected):
    data = {"email": "user@test.com", "password": PW, "csrf_token": token(client)}
    r = client.post(f"/login?next={nxt}", data=data)
    loc = r.headers["Location"]
    assert loc.startswith("/") and not loc.startswith("//") and "evil" not in loc
    assert loc == expected


def test_staff_next_cannot_cross_into_the_other_portal(client, users):
    data = {"email": "admin@test.com", "password": PW, "csrf_token": token(client, "/admin/login")}
    r = client.post("/admin/login?next=/owner/", data=data)
    assert r.headers["Location"] == "/admin/"


# ---------------- registration ----------------
def test_register_creates_a_customer_and_ignores_a_role_field(client, session):
    r = post(client, "/register", {"name": "New Person", "email": "New@Test.com", "phone": "+91 98765 43210",
                                   "password": "Passw0rdOK", "confirm": "Passw0rdOK", "role": "admin", "is_blocked": ""})
    assert r.status_code == 302 and r.headers["Location"] == "/account"
    u = session.scalar(select(User).where(User.email == "new@test.com"))
    assert u.role == "user" and u.phone == "9876543210" and u.password_hash.startswith("$argon2")
    assert client.get("/admin/").status_code == 403


@pytest.mark.parametrize("data,field", [
    ({"name": "A", "email": "a@test.com", "password": "Passw0rdOK", "confirm": "Passw0rdOK"}, "name"),
    ({"name": "Ann", "email": "not-an-email", "password": "Passw0rdOK", "confirm": "Passw0rdOK"}, "email"),
    ({"name": "Ann", "email": "a@test.com", "phone": "12345", "password": "Passw0rdOK", "confirm": "Passw0rdOK"}, "phone"),
    ({"name": "Ann", "email": "a@test.com", "password": "short1", "confirm": "short1"}, "password"),
    ({"name": "Ann", "email": "a@test.com", "password": "onlyletters", "confirm": "onlyletters"}, "password"),
    ({"name": "Ann", "email": "a@test.com", "password": "password123", "confirm": "password123"}, "password"),
    ({"name": "Ann", "email": "a@test.com", "password": "Passw0rdOK", "confirm": "Different1"}, "confirm"),
])
def test_register_validation_messages(client, session, data, field):
    r = post(client, "/register", data)
    assert r.status_code == 422
    assert f'id="{field}-err"' in r.get_data(as_text=True)
    assert session.scalar(select(User).where(User.email == "a@test.com")) is None


def test_register_rejects_duplicate_email_case_insensitively(client, users):
    r = post(client, "/register", {"name": "Dup", "email": "USER@test.com", "password": "Passw0rdOK", "confirm": "Passw0rdOK"})
    assert r.status_code == 422 and "already exists" in r.get_data(as_text=True)


# ---------------- headers, audit, pages ----------------
def test_security_headers_and_no_store_on_private_pages(client, users):
    r = client.get("/login")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    sign_in(client, "user")
    assert client.get("/account").headers["Cache-Control"] == "no-store"


def test_staff_sign_ins_and_failures_are_audited(client, users, session):
    sign_in(client, "admin", password="wrong-pass1")
    sign_in(client, "admin")
    actions = [a.action for a in session.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert "auth.failed_staff_login" in actions and "auth.login" in actions


def test_error_pages_render(client):
    r = client.get("/no-such-page")
    assert r.status_code == 404 and "Page not found" in r.get_data(as_text=True)


def test_pages_have_mobile_viewport_and_16px_inputs(client):
    html = client.get("/login").get_data(as_text=True)
    assert "viewport-fit=cover" in html and 'autocomplete="current-password"' in html and 'inputmode="email"' in html
    css = client.get("/static/css/base.css").get_data(as_text=True)
    assert "max(16px, 1rem)" in css and "--tap: 2.75rem" in css
