"""Step 5.2: rate limits live in Redis (when configured) and cover login, register, password reset, coupon, cart, pincode, contact."""
import os
import subprocess
import sys

import pytest

from app import ratelimits
from app.extensions import limiter
from tests.helpers import make_user, post, token
from tests.test_step6_shop import JSON, cust, catalog, pj  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def _fresh(session):
    """`session` empties the tables after each test, including the failed-login rows that would lock "nobody@x.com" out."""
    limiter.reset()


def limited(monkeypatch, app, **limits):
    for name, value in limits.items():
        monkeypatch.setitem(app.config["RATE_LIMITS"], name, value)


def statuses(fn, n):
    return [fn().status_code for _ in range(n)]


# ---------------------------------------------------------------- storage
def test_redis_uri_from_the_environment_is_actually_used():
    """The Limiter used to be built with storage_uri="memory://", which beat RATELIMIT_STORAGE_URI and kept Redis off."""
    code = ("from app import create_app; from app.extensions import limiter; app = create_app(); "
            "print(type(limiter.storage).__name__, limiter._storage_uri)")
    env = {**os.environ, "FLASK_ENV": "development", "SECRET_KEY": "k" * 48, "RATELIMIT_STORAGE_URI": "redis://127.0.0.1:6390/0"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-800:]
    assert out.stdout.split()[-2:] == ["RedisStorage", "None"]


def test_default_storage_is_memory_in_tests(app):
    assert type(limiter.storage).__name__ == "MemoryStorage"


def test_redis_outage_falls_back_instead_of_failing(app):
    assert app.config["RATELIMIT_IN_MEMORY_FALLBACK_ENABLED"] is True and app.config["RATELIMIT_HEADERS_ENABLED"] is True


def test_redis_client_library_is_a_requirement():
    assert any(line.startswith("redis") for line in open("requirements.txt"))


# ---------------------------------------------------------------- configuration
def test_every_limit_has_a_default_and_can_be_overridden(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_COUPON", "3 per minute")
    cfg = ratelimits.configured()
    assert set(cfg) == set(ratelimits.DEFAULTS) and cfg["coupon"] == "3 per minute"
    assert cfg["register"] == ratelimits.DEFAULTS["register"]


def test_all_required_areas_have_a_limit():
    for name in ("login_hourly", "register", "password_reset_request", "password_reset_email", "password_reset", "coupon",
                 "cart_add", "cart_change", "pincode", "contact"):
        assert ratelimits.DEFAULTS[name]


# ---------------------------------------------------------------- auth
@pytest.mark.parametrize("url", ["/login", "/owner/login", "/admin/login"])
def test_login_hourly_cap(app, monkeypatch, url):
    limited(monkeypatch, app, login_hourly="2 per hour")
    c = app.test_client()
    codes = statuses(lambda: post(c, url, {"email": "nobody@x.com", "password": "Wrong-pass1"}, page=url), 3)
    assert codes[:2] == [401, 401] and codes[2] == 429


def test_login_per_minute_limit_still_applies(app, monkeypatch):
    monkeypatch.setitem(app.config, "LOGIN_RATE_LIMIT", "2 per minute")
    c = app.test_client()
    codes = statuses(lambda: post(c, "/login", {"email": "n@x.com", "password": "Wrong-pass1"}, page="/login"), 3)
    assert codes == [401, 401, 429]


def test_register_limit(app, monkeypatch):
    limited(monkeypatch, app, register="2 per minute")
    c = app.test_client()
    codes = statuses(lambda: post(c, "/register", {"name": "A", "email": "bad"}, page="/register"), 3)
    assert codes == [422, 422, 429]


def test_429_tells_the_browser_when_to_retry(app, monkeypatch):
    limited(monkeypatch, app, register="1 per minute")
    c = app.test_client()
    post(c, "/register", {"name": "A"}, page="/register")
    r = post(c, "/register", {"name": "A"}, page="/register")
    assert r.status_code == 429 and r.headers.get("Retry-After")


def test_password_reset_request_per_ip(app, monkeypatch):
    limited(monkeypatch, app, password_reset_request="2 per minute")
    c = app.test_client()
    codes = [post(c, "/forgot", {"email": f"a{i}@x.com"}, page="/forgot").status_code for i in range(3)]
    assert codes[:2] == [200, 200] and codes[2] == 429


def test_password_reset_request_per_email_blocks_mail_bombing(app, monkeypatch):
    limited(monkeypatch, app, password_reset_email="2 per hour")
    c = app.test_client()
    codes = [post(c, "/forgot", {"email": "victim@x.com"}, page="/forgot").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert post(c, "/forgot", {"email": "someone-else@x.com"}, page="/forgot").status_code == 200   # other addresses unaffected
    assert post(c, "/forgot", {"email": "VICTIM@x.com "}, page="/forgot").status_code == 429       # same address, different spelling


def test_reset_link_attempts_are_limited(app, monkeypatch):
    limited(monkeypatch, app, password_reset="2 per minute")
    c = app.test_client()
    codes = []
    for _ in range(3):
        codes.append(c.post("/reset/not-a-token", data={"new": "x", "confirm": "x", "csrf_token": token(c, "/forgot")}).status_code)
    assert codes[:2] == [400, 400] and codes[2] == 429


# ---------------------------------------------------------------- shop
def test_coupon_apply_limit(app, monkeypatch, catalog):
    limited(monkeypatch, app, coupon="2 per minute")
    c = app.test_client()
    codes = [pj(c, "/cart/coupon", {"code": "NOPE"}).status_code for _ in range(3)]
    assert codes[:2] == [422, 422] and codes[2] == 429


def test_add_to_cart_limit_for_guests(app, monkeypatch, catalog):
    _, p = catalog
    limited(monkeypatch, app, cart_add="2 per minute")
    c = app.test_client()
    codes = [pj(c, "/cart/add", {"product_id": p.id}).status_code for _ in range(3)]
    assert codes[:2] == [200, 200] and codes[2] == 429


@pytest.mark.parametrize("action", ["qty", "remove", "save"])
def test_cart_change_limit(app, monkeypatch, catalog, action):
    _, p = catalog
    limited(monkeypatch, app, cart_change="2 per minute")
    c = app.test_client()
    pj(c, "/cart/add", {"product_id": p.id})
    codes = [pj(c, f"/cart/999999/{action}").status_code for _ in range(3)]
    assert codes[2] == 429 and 429 not in codes[:2]


def test_pincode_api_limit(app, monkeypatch):
    limited(monkeypatch, app, pincode="2 per minute")
    c = app.test_client()
    codes = statuses(lambda: c.get("/api/pincode/641001"), 3)
    assert codes[2] == 429 and 429 not in codes[:2]


def test_contact_form_limit(app, monkeypatch):
    limited(monkeypatch, app, contact="2 per minute")
    c = app.test_client()
    codes = statuses(lambda: post(c, "/help", {"name": "A"}, page="/help"), 3)
    assert codes[2] == 429 and 429 not in codes[:2]


def test_contact_form_get_is_not_limited(app, monkeypatch):
    limited(monkeypatch, app, contact="1 per minute")
    c = app.test_client()
    assert all(code == 200 for code in statuses(lambda: c.get("/help"), 4))
