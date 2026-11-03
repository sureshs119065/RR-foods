"""Step 8: the production safety net (refuses unsafe settings) and the /readyz health check."""
from types import SimpleNamespace

import pytest

from app import create_app
from app.config import TestConfig
from app.prodcheck import config_problems


def fake(**over):
    cfg = {"SECRET_KEY": "k" * 48, "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://shop:Zq8!x@db/nk", "ONLINE_PAYMENT_MODE": "off",
           "SESSION_COOKIE_SECURE": True, "DEBUG": False, "RATELIMIT_STORAGE_URI": "redis://r/0", "SITE_URL": "https://shop.example.com",
           "TRUST_PROXY": True, "MAIL_MODE": "smtp", "MAIL_SERVER": "smtp.example.com", "UPLOAD_DIR": "/srv/uploads"}
    cfg.update(over)
    return SimpleNamespace(config=cfg)


def test_good_settings_have_nothing_to_fix_or_advise():
    assert config_problems(fake()) == ([], [])


@pytest.mark.parametrize("over", [
    {"SECRET_KEY": "dev-only-change-me"}, {"SECRET_KEY": "short"},
    {"SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://nk_user:nk_password@localhost/nk"},
    {"ONLINE_PAYMENT_MODE": "stub"}, {"SESSION_COOKIE_SECURE": False}, {"DEBUG": True},
])
def test_each_dangerous_setting_is_fatal(over):
    fatal, _ = config_problems(fake(**over))
    assert len(fatal) == 1


def test_softer_problems_are_advice_only():
    fatal, advice = config_problems(fake(RATELIMIT_STORAGE_URI="memory://", SITE_URL="http://x", TRUST_PROXY=False, MAIL_MODE="off",
                                         UPLOAD_DIR="uploads"))
    assert fatal == [] and len(advice) == 5


def test_production_start_is_refused_with_a_weak_key(monkeypatch):
    class Weak(TestConfig):
        TESTING = False
        SECRET_KEY = "short"
    monkeypatch.setenv("FLASK_ENV", "production")
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        create_app(Weak)


def test_development_start_is_not_blocked(monkeypatch):
    class Weak(TestConfig):
        TESTING = False
        SECRET_KEY = "short"
    monkeypatch.setenv("FLASK_ENV", "development")
    assert create_app(Weak) is not None


def test_readyz_and_healthz(app):
    c = app.test_client()
    assert c.get("/healthz").get_json() == {"status": "ok"}
    r = c.get("/readyz")
    assert r.status_code == 200 and r.get_json() == {"status": "ready"}
