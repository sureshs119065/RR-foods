"""Production safety check. Used at startup (refuses to run with unsafe settings) and by `flask check-config`.

fatal  = the site must not start like this (a real customer could be harmed).
advice = works, but you should fix it before real customers arrive.
"""
import os

EXAMPLE_PASSWORDS = ("nk_password",)
EXAMPLE_KEYS = ("dev-only-change-me", "change-me-to-a-long-random-string", "test-secret")


def is_production(app) -> bool:
    return os.environ.get("FLASK_ENV") == "production" and not app.config.get("TESTING")


ALLOWED_ENVS = ("production", "development")


def startup_errors(app) -> list[str]:
    """Hard requirements checked by create_app() outside tests: a secret key and an explicit FLASK_ENV."""
    errors = []
    if not app.config.get("SECRET_KEY"):
        errors.append("SECRET_KEY is not set. There is no default. Generate one with:  "
                      "python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    env = os.environ.get("FLASK_ENV")
    if env not in ALLOWED_ENVS:
        errors.append(f"FLASK_ENV is {env!r}. Set FLASK_ENV=production on the server (or FLASK_ENV=development for local work).")
    return errors


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

    if str(c.get("RATELIMIT_STORAGE_URI", "")).startswith("memory") and not c.get("ALLOW_MEMORY_RATELIMIT"):
        fatal.append("RATELIMIT_STORAGE_URI is in-memory. Limits would be per worker, so with several workers an attacker gets several "
                     "times the limit and a restart clears them. Set RATELIMIT_STORAGE_URI=redis://localhost:6379/0 "
                     "(Render: a Key Value instance), or ALLOW_MEMORY_RATELIMIT=1 to accept the risk knowingly.")
    if not str(c.get("SITE_URL", "")).startswith("https://"):
        advice.append("SITE_URL is not https://. Links in emails (password reset) should use your real https address.")
    if not c.get("TRUST_PROXY"):
        advice.append("TRUST_PROXY is not 1. Behind nginx or a load balancer set TRUST_PROXY=1, otherwise every visitor looks like "
                      "the same IP (rate limits and login lockout then hit everybody at once).")
    if c.get("MAIL_MODE") != "smtp":
        advice.append("MAIL_MODE is not smtp, so password-reset and order emails will not be delivered.")
    elif not c.get("MAIL_SERVER"):
        advice.append("MAIL_MODE=smtp but MAIL_SERVER is empty.")
    if not c.get("SECURITY_CONTACT"):
        advice.append("SECURITY_CONTACT is empty, so /.well-known/security.txt answers 404. Set it to an email address you read, "
                      "for example SECURITY_CONTACT=security@your-domain.in.")
    if not (c.get("ADMIN_WHATSAPP_NUMBER") or c.get("WHATSAPP_NUMBER")):
        advice.append("ADMIN_WHATSAPP_NUMBER is empty. Customers cannot send their order to the shop on WhatsApp. "
                      "Set it with the country code, digits only, for example ADMIN_WHATSAPP_NUMBER=919876543210.")
    manifest = getattr(app, "extensions", {}).get("asset_manifest")  # {} = the app started without a build; None = not a real app
    if manifest is not None and not manifest:
        advice.append("static/dist/manifest.json is missing, so pages load the large unminified CSS and JavaScript. Run "
                      "`python tools/build_assets.py` in the build step (Render: Build command).")
    if not os.path.isabs(str(c.get("UPLOAD_DIR", ""))):
        advice.append("UPLOAD_DIR is relative. Use an absolute path on a disk that is backed up.")
    if _inside_code(c.get("UPLOAD_DIR")):
        fatal.append("UPLOAD_DIR is inside the application folder (code, templates or static files). Uploads must live outside it, "
                     "for example UPLOAD_DIR=/var/data/uploads, so nothing uploaded can ever be served or run as code.")
    return fatal, advice


def _inside_code(upload_dir) -> bool:
    """True when the upload folder is the app package itself or below it (app/, app/static, app/templates ...)."""
    from pathlib import Path
    if not upload_dir:
        return False
    code = Path(__file__).resolve().parent
    target = Path(str(upload_dir)).resolve()
    return target == code or code in target.parents


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
