import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _db_url(url: str) -> str:
    """Render/Heroku give postgres:// or postgresql://; SQLAlchemy needs the psycopg driver named."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = _db_url(os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://nk_user:nk_password@localhost:5432/nk"
    ))
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    UPLOAD_DIR = str(BASE_DIR / os.environ.get("UPLOAD_DIR", "uploads"))
    # per-request cap (several images at once). Each single image is limited to 5 MB in app/uploads.py
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "60")) * 1024 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"
    JSON_SORT_KEYS = False
    SHOP_TIMEZONE = os.environ.get("SHOP_TIMEZONE", "Asia/Kolkata")  # times typed in the admin panel are in this zone

    # --- auth ---
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)  # customers stay signed in
    STAFF_IDLE_MINUTES = int(os.environ.get("STAFF_IDLE_MINUTES", "60"))  # owner/admin sign out after this much inactivity
    MAX_FAILED_LOGINS = 5
    LOCKOUT_MINUTES = 15
    LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "10 per minute")
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")  # use redis:// in production
    # WhatsApp-first ordering (no API, no cost): the order is sent to this number as a ready-written WhatsApp message and the
    # owner settles payment with the customer on WhatsApp. Digits only, with country code, e.g. 919876543210.
    ADMIN_WHATSAPP_NUMBER = os.environ.get("ADMIN_WHATSAPP_NUMBER", "")
    DEFAULT_COUNTRY_CODE = os.environ.get("DEFAULT_COUNTRY_CODE", "91")  # added to 10 digit customer numbers
    SHOP_NAME = os.environ.get("SHOP_NAME", "RR FOODS")
    # email: "off" (send nothing), "console" (print to the terminal, for testing), "smtp" (real). Run `flask send-emails` every minute from cron.
    MAIL_MODE = os.environ.get("MAIL_MODE", "off" if os.environ.get("FLASK_ENV") == "production" else "console")
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
    MAIL_FROM = os.environ.get("MAIL_FROM", "RR FOODS <no-reply@example.com>")
    WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "")
    SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "")
    SITE_URL = os.environ.get("SITE_URL", "http://localhost:5000").rstrip("/")  # used for links inside emails
    # scrolling bar above the header. Separate messages with "|". Leave empty to hide the bar. Only list things that are true.
    ANNOUNCEMENTS = [a.strip() for a in os.environ.get("ANNOUNCEMENTS", "").split("|") if a.strip()]
    TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"  # set when running behind nginx/a load balancer


class TestConfig(Config):
    TESTING = True
    UPLOAD_DIR = "/tmp/nk-test-uploads"
    SECRET_KEY = "test-secret"
    MAIL_MODE = "console"
    LOGIN_RATE_LIMIT = "1000 per minute"  # high so normal tests never trip it; one test lowers it
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/nk_test"
    )
