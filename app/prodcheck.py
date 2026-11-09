"""Production safety check. Used at startup (refuses to run with unsafe settings) and by `flask check-config`.

fatal  = the site must not start like this (a real customer could be harmed).
advice = works, but you should fix it before real customers arrive.
"""
import os

EXAMPLE_PASSWORDS = ("nk_password",)
EXAMPLE_KEYS = ("dev-only-change-me", "change-me-to-a-long-random-string", "test-secret")


def is_production(app) -> bool:
    return os.environ.get("FLASK_ENV") == "production" and not app.config.get("TESTING")


def config_problems(app) -> tuple[list[str], list[str]]:
    c = app.config
    fatal, advice = [], []

    key = c.get("SECRET_KEY") or ""
    if len(key) < 32 or key in EXAMPLE_KEYS:
        fatal.append("SECRET_KEY is missing, left at the example value, or shorter than 32 characters. Generate one with:  "
                     "python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    uri = str(c.get("SQLALCHEMY_DATABASE_URI") or "")
    if any(p in uri for p in EXAMPLE_PASSWORDS):
        fatal.append("DATABASE_URL still uses the example database password. Create a real database user with a strong password.")
    if not c.get("SESSION_COOKIE_SECURE"):
        fatal.append("SESSION_COOKIE_SECURE is off. Set FLASK_ENV=production and serve the site over HTTPS.")
    if c.get("DEBUG"):
        fatal.append("DEBUG is on. Never run debug mode in production.")

    if str(c.get("RATELIMIT_STORAGE_URI", "")).startswith("memory"):
        advice.append("RATELIMIT_STORAGE_URI is in-memory. Limits are per worker, so with several workers an attacker gets several "
                      "times the limit. Set RATELIMIT_STORAGE_URI=redis://localhost:6379/0.")
    if not str(c.get("SITE_URL", "")).startswith("https://"):
        advice.append("SITE_URL is not https://. Links in emails (password reset) should use your real https address.")
    if not c.get("TRUST_PROXY"):
        advice.append("TRUST_PROXY is not 1. Behind nginx or a load balancer set TRUST_PROXY=1, otherwise every visitor looks like "
                      "the same IP (rate limits and login lockout then hit everybody at once).")
    if c.get("MAIL_MODE") != "smtp":
        advice.append("MAIL_MODE is not smtp, so password-reset and order emails will not be delivered.")
    elif not c.get("MAIL_SERVER"):
        advice.append("MAIL_MODE=smtp but MAIL_SERVER is empty.")
    if not (c.get("ADMIN_WHATSAPP_NUMBER") or c.get("WHATSAPP_NUMBER")):
        advice.append("ADMIN_WHATSAPP_NUMBER is empty. Customers cannot send their order to the shop on WhatsApp. "
                      "Set it with the country code, digits only, for example ADMIN_WHATSAPP_NUMBER=919876543210.")
    if not os.path.isabs(str(c.get("UPLOAD_DIR", ""))):
        advice.append("UPLOAD_DIR is relative. Use an absolute path on a disk that is backed up.")
    return fatal, advice


def example_accounts_advice() -> str | None:
    """Looks in the database for the seeded @nurseskitchen.local accounts (call inside an app context)."""
    from sqlalchemy import select

    from .extensions import db
    from .models import User

    rows = db.session.scalars(select(User.email).where(User.email.like("%@nurseskitchen.local"), User.is_blocked.is_(False))).all()
    if rows:
        return ("These accounts use the example '@nurseskitchen.local' address. Create real staff accounts "
                "(flask create-user ...) and block the examples from Admin > Users: " + ", ".join(sorted(rows)))
    return None
