"""One place for every rate limit (step 5.2).

Each value is a Flask-Limiter string; ";" joins several windows (all must pass). Limits are per client IP and per
endpoint, and live in Redis (RATELIMIT_STORAGE_URI) so every gunicorn worker shares them. Override any one with an
environment variable named RATE_LIMIT_<NAME>, for example RATE_LIMIT_COUPON="5 per minute".
"""
import os

from flask import current_app, request

DEFAULTS = {
    "login_hourly": "100 per hour",              # added to LOGIN_RATE_LIMIT (per minute) for /login, /owner/login, /admin/login
    "register": "5 per minute;20 per hour",
    "password_reset_request": "5 per minute;10 per hour",   # per IP; password_reset_email below is per address
    "password_reset_email": "3 per hour",        # stops one inbox being mail-bombed from many IPs
    "password_reset": "10 per minute;30 per hour",           # the emailed link
    "coupon": "10 per minute;60 per hour",
    "cart_add": "60 per minute;600 per hour",
    "cart_change": "120 per minute",             # quantity, remove, save for later
    "pincode": "60 per minute;600 per hour",
    "contact": "5 per minute;20 per hour",       # /help enquiry form
    "csp_report": "30 per minute",
    "otp_send": "10 per minute;40 per hour",       # per IP, on top of the per-email and per-IP hourly caps kept in the email_otp table
    "otp_verify": "20 per minute;100 per hour",
}


def configured() -> dict:
    """Defaults with any RATE_LIMIT_<NAME> environment override applied (used by Config)."""
    return {k: os.environ.get("RATE_LIMIT_" + k.upper()) or v for k, v in DEFAULTS.items()}


def limit(name: str):
    """A callable for @limiter.limit(...): reads the current value on every request, so tests and ops can change it."""
    def _value() -> str:
        return (current_app.config.get("RATE_LIMITS") or {}).get(name) or DEFAULTS[name]
    return _value


def email_key() -> str:
    """Limiter key for per-address limits: the (normalised, capped) email in the submitted form."""
    return "email:" + (request.form.get("email", "") or "").strip().lower()[:255]
