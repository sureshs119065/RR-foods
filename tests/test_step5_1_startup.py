"""Step 5.1: no default SECRET_KEY, explicit FLASK_ENV, Secure cookies and HSTS in production."""
import importlib

import pytest

from app import create_app
from app.config import TestConfig

GOOD_KEY = "k" * 48


class Live(TestConfig):
    """Like TestConfig but not in testing mode, so the startup rules apply."""
    TESTING = False
    SECRET_KEY = GOOD_KEY
    SESSION_COOKIE_SECURE = True
    ALLOW_MEMORY_RATELIMIT = True   # 5.2 made an in-memory limiter fatal in production; these tests are about other rules
    UPLOAD_DIR = "/tmp/nk-test-uploads"


def test_config_has_no_default_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    import app.config as cfg
    try:
        importlib.reload(cfg)
        assert cfg.Config.SECRET_KEY is None
    finally:
        monkeypatch.undo()
        importlib.reload(cfg)


def test_empty_secret_key_env_is_not_a_key(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "")
    import app.config as cfg
    try:
        importlib.reload(cfg)
        assert cfg.Config.SECRET_KEY is None
    finally:
        monkeypatch.undo()
        importlib.reload(cfg)


@pytest.mark.parametrize("env", ["production", "development"])
def test_start_refused_without_secret_key(monkeypatch, env):
    class NoKey(Live):
        SECRET_KEY = None
    monkeypatch.setenv("FLASK_ENV", env)
    with pytest.raises(RuntimeError, match="SECRET_KEY is not set"):
        create_app(NoKey)


@pytest.mark.parametrize("env", [None, "", "staging", "testing"])
def test_start_refused_without_explicit_flask_env(monkeypatch, env):
    if env is None:
        monkeypatch.delenv("FLASK_ENV", raising=False)
    else:
        monkeypatch.setenv("FLASK_ENV", env)
    with pytest.raises(RuntimeError, match="FLASK_ENV"):
        create_app(Live)


def test_tests_may_start_without_either(monkeypatch):
    class Bare(TestConfig):
        SECRET_KEY = None
    monkeypatch.delenv("FLASK_ENV", raising=False)
    assert create_app(Bare) is not None   # TESTING=True is exempt


def test_check_config_command_can_still_start(monkeypatch):
    class NoKey(Live):
        SECRET_KEY = None
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.setattr("sys.argv", ["flask", "check-config"])
    assert create_app(NoKey) is not None


def test_development_with_a_key_starts(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    assert create_app(Live) is not None


def test_production_cookie_is_secure_even_if_env_says_off(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    import app.config as cfg
    try:
        importlib.reload(cfg)
        assert cfg.Config.SESSION_COOKIE_SECURE is True
    finally:
        monkeypatch.undo()
        importlib.reload(cfg)


def test_development_cookie_is_not_secure_by_default(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    import app.config as cfg
    try:
        importlib.reload(cfg)
        assert cfg.Config.SESSION_COOKIE_SECURE is False
    finally:
        monkeypatch.undo()
        importlib.reload(cfg)


def test_production_sends_hsts_even_when_the_proxy_hides_https(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    app = create_app(Live)
    r = app.test_client().get("/healthz")   # plain http, as seen behind a proxy without TRUST_PROXY
    assert r.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_hsts_can_be_turned_off_with_zero(monkeypatch):
    class NoHsts(Live):
        HSTS_SECONDS = 0
    monkeypatch.setenv("FLASK_ENV", "production")
    r = create_app(NoHsts).test_client().get("/healthz")
    assert "Strict-Transport-Security" not in r.headers


def test_development_does_not_send_hsts(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    r = create_app(Live).test_client().get("/healthz")
    assert "Strict-Transport-Security" not in r.headers


def test_testing_mode_never_sends_hsts(app):
    assert "Strict-Transport-Security" not in app.test_client().get("/healthz").headers
