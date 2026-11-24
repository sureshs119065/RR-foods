import os
from datetime import timedelta
from pathlib import Path

from .ratelimits import configured as _rate_limits

BASE_DIR = Path(__file__).resolve().parent.parent


def _db_url(url: str) -> str:
    """Render/Heroku give postgres:// or postgresql://; SQLAlchemy needs the psycopg driver named."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


IS_PRODUCTION = os.environ.get("FLASK_ENV") == "production"


class Config:
    # No default on purpose: create_app() refuses to start without one (tests use TestConfig.SECRET_KEY).
    SECRET_KEY = os.environ.get("SECRET_KEY") or None
    SQLALCHEMY_DATABASE_URI = _db_url(os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://nk_user:nk_password@localhost:5432/nk"
    ))
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    UPLOAD_DIR = str(BASE_DIR / os.environ.get("UPLOAD_DIR", "uploads"))
    # per-request cap (several images at once). Each single image is limited to 5 MB in app/uploads.py
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "60")) * 1024 * 1024
    # step 5.5: customers (review photos) get a smaller whole-request cap than admin/owner uploads
    CUSTOMER_MAX_CONTENT_LENGTH = int(os.environ.get("CUSTOMER_MAX_UPLOAD_MB", "16")) * 1024 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Production always gets Secure cookies (the env var cannot switch it off there); elsewhere it is opt-in.
    SESSION_COOKIE_SECURE = IS_PRODUCTION or os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    HSTS_SECONDS = int(os.environ.get("HSTS_SECONDS", "31536000"))  # sent on every response in production (0 = off)
    JSON_SORT_KEYS = False
    SHOP_TIMEZONE = os.environ.get("SHOP_TIMEZONE", "Asia/Kolkata")  # times typed in the admin panel are in this zone

    # --- auth ---
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)  # customers stay signed in
    STAFF_IDLE_MINUTES = int(os.environ.get("STAFF_IDLE_MINUTES", "60"))  # owner/admin sign out after this much inactivity
    MAX_FAILED_LOGINS = 5
    LOCKOUT_MINUTES = 15
    LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "10 per minute")
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")  # production needs redis:// (see prodcheck)
    ALLOW_MEMORY_RATELIMIT = os.environ.get("ALLOW_MEMORY_RATELIMIT") == "1"  # explicit opt-out of the Redis requirement
    RATELIMIT_IN_MEMORY_FALLBACK_ENABLED = True   # if Redis is down, fall back to per-worker counting instead of erroring
    RATELIMIT_HEADERS_ENABLED = True              # Retry-After on 429
    RATE_LIMITS = _rate_limits()                  # every other limit, see app/ratelimits.py
    # WhatsApp-first ordering (no API, no cost): the order is sent to this number as a ready-written WhatsApp message and the
    # owner settles payment with the customer on WhatsApp. Digits only, with country code, e.g. 919876543210.
    ADMIN_WHATSAPP_NUMBER = os.environ.get("ADMIN_WHATSAPP_NUMBER", "")
    DEFAULT_COUNTRY_CODE = os.environ.get("DEFAULT_COUNTRY_CODE", "91")  # added to 10 digit customer numbers
    SHOP_NAME = os.environ.get("SHOP_NAME", "RR FOODS")
    # email: "off" (send nothing), "console" (print to the terminal, for testing), "smtp" (real), "brevo" / "resend" (HTTPS API). Run `flask send-emails` every minute from cron.
    MAIL_MODE = os.environ.get("MAIL_MODE", "off" if os.environ.get("FLASK_ENV") == "production" else "console")
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
    MAIL_FROM = os.environ.get("MAIL_FROM", "RR FOODS <no-reply@example.com>")
    MAIL_SENDER_NAME = os.environ.get("MAIL_SENDER_NAME", "RR FOODS")   # display name on the sign-in code email
    BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")      # MAIL_MODE=brevo: email over HTTPS, works on Render's free plan
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")    # MAIL_MODE=resend
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "0") == "1"           # implicit TLS (port 465); leave 0 for STARTTLS on 587
    # customer email sign-in codes
    OTP_TTL_SECONDS = int(os.environ.get("OTP_TTL_SECONDS", "300"))              # a code works for 5 minutes
    OTP_MAX_ATTEMPTS = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))              # wrong guesses before the code is thrown away
    OTP_RESEND_SECONDS = int(os.environ.get("OTP_RESEND_SECONDS", "45"))         # wait between two codes for one email
    OTP_MAX_PER_EMAIL_HOUR = int(os.environ.get("OTP_MAX_PER_EMAIL_HOUR", "5"))
    OTP_MAX_PER_IP_HOUR = int(os.environ.get("OTP_MAX_PER_IP_HOUR", "10"))
    WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "")
    SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "")
    SHOP_ADDRESS = os.environ.get("SHOP_ADDRESS", "")   # shown on the Contact page when set
    SHOP_HOURS = os.environ.get("SHOP_HOURS", "")       # e.g. "Mon-Sat, 9 AM - 7 PM"
    SECURITY_CONTACT = os.environ.get("SECURITY_CONTACT", "")   # step 5.7: published in /.well-known/security.txt (email, mailto: or https URL)
    SECURITY_TXT_EXPIRES = os.environ.get("SECURITY_TXT_EXPIRES", "")   # optional fixed ISO date; default is rolling now+180 days
    SITE_URL = os.environ.get("SITE_URL", "http://localhost:5000").rstrip("/")  # used for links inside emails
    # scrolling bar above the header. Separate messages with "|". Leave empty to hide the bar. Only list things that are true.
    ANNOUNCEMENTS = [a.strip() for a in os.environ.get("ANNOUNCEMENTS", "").split("|") if a.strip()]
    TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"
    APP_VERSION = os.environ.get("APP_VERSION", "1.0.0")
    LOG_DIR = str(BASE_DIR / os.environ.get("LOG_DIR", "logs"))
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", "5242880"))
    LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", "5"))
    LOGIN_IP_LOCKOUT_ENABLED = os.environ.get("LOGIN_IP_LOCKOUT_ENABLED", "1") == "1"
    LOGIN_IP_MAX_FAILED = int(os.environ.get("LOGIN_IP_MAX_FAILED", "12"))
    HOME_CACHE_SECONDS = int(os.environ.get("HOME_CACHE_SECONDS", "60"))  # per-worker cache of home categories / new arrivals; 0 = off
    VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
    VAPID_CLAIMS_EMAIL = os.environ.get("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com")  # set when running behind nginx/a load balancer


class TestConfig(Config):
    TESTING = True
    UPLOAD_DIR = "/tmp/nk-test-uploads"
    SECRET_KEY = "test-secret"
    MAIL_MODE = "console"
    HOME_CACHE_SECONDS = 0  # off so tests see their own writes; tests/test_step4_home_cache.py turns it on
    LOGIN_RATE_LIMIT = "1000 per minute"  # high so normal tests never trip it; one test lowers it
    RATE_LIMITS = {**Config.RATE_LIMITS, "login_hourly": "100000 per hour", "register": "1000 per minute", "password_reset_email": "1000 per hour",
                   "contact": "1000 per minute"}   # forgot-password (5/min) and the rest keep their real values so the old test still covers them
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/nk_test"
    )
