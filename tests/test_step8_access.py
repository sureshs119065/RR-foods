"""Step 8: access control over EVERY route, found automatically from the URL map.

If a developer adds a new /admin or /owner page and forgets the decorator, this file fails. Nothing here changes real data:
parameters are filled with ids that do not exist.
"""
import os

import pytest
from flask import url_for
from werkzeug.routing import IntegerConverter

from tests.helpers import make_user, sign_in, token

ROLES = ("user", "owner", "admin")
DASH = {"user": "/account", "owner": "/owner/", "admin": "/admin/"}
LOGIN_PAGES = {"/login", "/owner/login", "/admin/login"}
# pages anybody may open without signing in (a new public page must be added here on purpose)
PUBLIC_GET = {"/", "/shop", "/category/<slug>", "/product/<slug>", "/offers", "/compare", "/offline", "/sw.js", "/manifest.webmanifest",
              "/robots.txt", "/sitemap.xml", "/healthz", "/readyz", "/api/header-banners", "/api/pincode/<pin>", "/api/suggest",
              "/banner-colors.css", "/uploads/<path:filename>", "/login", "/owner/login", "/admin/login", "/register", "/forgot",
              "/reset/<token>", "/about", "/bestsellers", "/bundles", "/help", "/recipes", "/recipes/<slug>", "/health", "/favicon.ico",
              "/push/vapid-public-key"}
# public POSTs: sign-in forms, sign-up, compare toggle and the Help page message form (no account needed), password-reset forms
PUBLIC_POST = {"/login", "/owner/login", "/admin/login", "/register", "/forgot", "/reset/<token>", "/compare/toggle", "/help"}


def _routes(app):
    out = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static" or rule.endpoint == "auth.logout":   # logout would sign the probe client out
            continue
        values = {a: (999999 if isinstance(rule._converters[a], IntegerConverter) else "x") for a in rule.arguments}
        with app.test_request_context():
            url = url_for(rule.endpoint, **values)
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            out.append((method, str(rule), url))
    return sorted(out)


def _fire(client, method, url, page):
    if method == "GET":
        return client.get(url)
    return client.post(url, data={"csrf_token": token(client, page)})


@pytest.fixture()
def clients(app, session):
    for r in ROLES:
        make_user(session, r)
    out = {None: app.test_client()}
    for r in ROLES:
        c = app.test_client()
        assert sign_in(c, r).status_code == 302
        out[r] = c
    return out


def test_route_inventory_is_not_empty(app):
    assert len(_routes(app)) > 100


def test_no_route_ever_returns_a_server_error(app, clients):
    """Anonymous, user, owner and admin: nothing may answer 5xx, whatever the route or the (missing) data."""
    bad = []
    for method, rule, url in _routes(app):
        for role, c in clients.items():
            page = "/login" if role is None else DASH[role]
            code = _fire(c, method, url, page).status_code
            if code >= 500:
                bad.append(f"{role or 'anon'} {method} {url} -> {code}")
    assert not bad, "\n".join(bad)


def test_admin_pages_are_admin_only(app, clients):
    bad = []
    for method, rule, url in _routes(app):
        if not rule.startswith("/admin") or rule == "/admin/login":
            continue
        for role, c in clients.items():
            if role == "admin":
                continue
            code = _fire(c, method, url, "/login" if role is None else DASH[role]).status_code
            ok = code in (302, 401) if role is None else code == 403
            if not ok:
                bad.append(f"{role or 'anon'} {method} {url} -> {code}")
    assert not bad, "\n".join(bad)


def test_owner_pages_are_owner_only(app, clients):
    bad = []
    for method, rule, url in _routes(app):
        if not rule.startswith("/owner") or rule == "/owner/login":
            continue
        for role, c in clients.items():
            if role == "owner":
                continue
            code = _fire(c, method, url, "/login" if role is None else DASH[role]).status_code
            ok = code in (302, 401) if role is None else code == 403
            if not ok:
                bad.append(f"{role or 'anon'} {method} {url} -> {code}")
    assert not bad, "\n".join(bad)


def test_every_other_page_needs_sign_in_unless_listed_public(app, clients):
    """Customer pages (account, cart, checkout, orders, reviews...) must send visitors to the login page."""
    bad = []
    anon = clients[None]
    for method, rule, url in _routes(app):
        if rule.startswith(("/admin", "/owner")):
            continue
        public = (rule in PUBLIC_GET) if method == "GET" else (rule in PUBLIC_POST)
        if public:
            continue
        code = _fire(anon, method, url, "/login").status_code
        if code not in (302, 401, 403):
            bad.append(f"anon {method} {url} -> {code} (expected a redirect to sign in)")
    assert not bad, "\n".join(bad)


def test_staff_cannot_use_the_customer_shop(app, clients):
    """Owners and admins have no cart, wishlist, orders or checkout."""
    bad = []
    for method, rule, url in _routes(app):
        if not rule.startswith(("/cart", "/checkout", "/account/orders", "/account/wishlist", "/wishlist", "/pay/")):
            continue
        for role in ("owner", "admin"):
            code = _fire(clients[role], method, url, DASH[role]).status_code
            if code == 200:
                bad.append(f"{role} {method} {url} -> 200")
    assert not bad, "\n".join(bad)


def test_error_pages_use_the_site_layout(app, clients):
    r = clients[None].get("/no-such-page")
    assert r.status_code == 404 and "<html" in r.get_data(as_text=True).lower()
    r = clients["user"].get("/admin/")
    assert r.status_code == 403 and "<html" in r.get_data(as_text=True).lower()
    assert "Traceback" not in r.get_data(as_text=True)


def test_security_headers_and_cookies(app, clients):
    r = clients[None].get("/")
    h = r.headers
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert "frame-ancestors" in h.get("Content-Security-Policy", "") or h.get("X-Frame-Options")
    cookies = " ".join(r.headers.getlist("Set-Cookie")) or " ".join(clients["user"].get("/account").headers.getlist("Set-Cookie"))
    assert "HttpOnly" in cookies or cookies == ""
