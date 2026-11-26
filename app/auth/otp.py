"""Customer sign-in AND sign-up verification with a code sent by email (Swiggy / Amazon style).

The code engine in this file (`issue_code` / `check_code`) is shared: /login/otp/* uses it with purpose "otp", and the create-account
flow (signup.py) uses it with purpose "signup". The purpose is mixed into the stored hash, so a code emailed for one cannot be used for the other.

Only the customer login page uses this. Owner and admin accounts can never be signed in here: they get the same replies as an
unknown address, no code is emailed to them and a code can never be verified for them.

Rules (all of them live in this file):
* The 6 digit code comes from `secrets`; only an HMAC-SHA256 of (email + code), keyed with SECRET_KEY, is stored in email_otp.
* A code works for OTP_TTL_SECONDS (5 minutes), for one sign-in, with at most OTP_MAX_ATTEMPTS wrong guesses.
* One new code per email every OTP_RESEND_SECONDS; at most OTP_MAX_PER_EMAIL_HOUR per email and OTP_MAX_PER_IP_HOUR per IP per hour.
* The reply to "send code" is the same for every well-formed address, so it cannot be used to find out who has an account. For an
  address that must not get a code (staff, blocked, deleted) a row is still written with a hash of a code nobody was sent, so the
  cooldown, the hourly caps and the 5-guess lock behave exactly as they do for a real customer.
"""
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from flask import current_app, flash, g, jsonify, request
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from .. import ratelimits as limits
from .. import validation as v
from ..extensions import db, limiter
from ..models import EmailOtp, User
from ..models.base import utcnow
from ..security import hash_password
from ..services.mailer import MailUnavailable, send_now
from .passwords import normalize_email, valid_email
from .routes import bp
from .service import audit, login_user, safe_next

GENERIC_SENT = "If this email can receive a code, we have sent a 6 digit code to it. It is valid for 5 minutes."
BAD_CODE = "That code is incorrect or has expired. Check the code or ask for a new one."


class CodeError(Exception):
    """A code could not be issued or verified. `message` is safe to show; `extra` carries flags such as retry_after / expired / locked."""

    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra


def _hash(email: str, code: str, purpose: str = "otp") -> str:
    return hmac.new(current_app.config["SECRET_KEY"].encode(), f"{purpose}:{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _may_get_code(user: User | None) -> bool:
    """A new address (becomes a customer on first sign-in) or an active customer. Never staff, blocked or deleted accounts."""
    return user is None or (user.role == "user" and not user.is_deleted and not user.is_blocked)


def _data() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else request.form.to_dict()


def _fail(message: str, status: int = 400, **extra):
    return jsonify(ok=False, message=message, **extra), status


def _email_parts(code: str, note: str = "") -> tuple[str, str, str]:
    minutes = max(1, current_app.config["OTP_TTL_SECONDS"] // 60)
    subject = f"{code} is your RR FOODS verification code"
    text = (f"Your RR FOODS verification code is {code}. {note + ' ' if note else ''}It is valid for {minutes} minutes. Do not share it with anyone.\n\n"
            "If you did not ask for this code, you can ignore this email.\n\nRR FOODS")
    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#f3f8f4;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f8f4;padding:24px 12px;"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:480px;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #d9e7dd;">
<tr><td style="background:#183d2b;padding:20px 24px;color:#ffffff;font-size:22px;font-weight:bold;letter-spacing:.5px;">RR FOODS</td></tr>
<tr><td style="padding:28px 24px 8px;color:#20352a;font-size:16px;line-height:1.5;">Your RR FOODS verification code is</td></tr>
<tr><td align="center" style="padding:8px 24px 16px;"><div style="display:inline-block;background:#eaf5ed;border:1px dashed #0f7b3e;border-radius:12px;padding:14px 28px;font-size:34px;font-weight:bold;letter-spacing:10px;color:#0f7b3e;">{code}</div></td></tr>
<tr><td style="padding:0 24px 8px;color:#20352a;font-size:15px;line-height:1.5;">{note + ' ' if note else ''}It is valid for <b>{minutes} minutes</b>. Do not share it with anyone.</td></tr>
<tr><td style="padding:8px 24px 28px;color:#6b7c72;font-size:13px;line-height:1.5;">If you did not ask for this code, you can safely ignore this email.</td></tr>
<tr><td style="background:#f3f8f4;padding:14px 24px;color:#6b7c72;font-size:12px;">Healthy, home-style food from RR FOODS</td></tr>
</table></td></tr></table></body></html>"""
    return subject, text, html


def issue_code(email: str, *, purpose: str = "otp", sendable: bool = True, note: str = "",
               unavailable: str = "Email sign-in is not available right now. Please sign in with your password instead.") -> dict:
    """Create and email a code. Applies the resend cooldown and the per-email / per-IP hourly caps.

    Returns {"cooldown": seconds, "expires_in": seconds}. Raises CodeError (already committed) when the caller must show a message.
    With sendable=False a row is still written, with a hash of a code nobody was sent, so the limits behave exactly as for a real address.
    """
    cfg = current_app.config
    now = utcnow()
    ip = (request.remote_addr or "")[:45]
    db.session.execute(delete(EmailOtp).where(EmailOtp.expires_at < now - timedelta(days=1)))   # clean up old codes

    last = db.session.scalar(select(EmailOtp).where(EmailOtp.email == email).order_by(EmailOtp.created_at.desc()).limit(1))
    if last is not None:
        wait = cfg["OTP_RESEND_SECONDS"] - int((now - last.created_at).total_seconds())
        if wait > 0:
            db.session.commit()
            raise CodeError(f"Please wait {wait} seconds before asking for another code.", 429, retry_after=wait)
    hour_ago = now - timedelta(hours=1)
    per_email = db.session.scalar(select(func.count(EmailOtp.id)).where(EmailOtp.email == email, EmailOtp.created_at > hour_ago)) or 0
    per_ip = db.session.scalar(select(func.count(EmailOtp.id)).where(EmailOtp.ip_address == ip, EmailOtp.created_at > hour_ago)) or 0 if ip else 0
    if per_email >= cfg["OTP_MAX_PER_EMAIL_HOUR"] or per_ip >= cfg["OTP_MAX_PER_IP_HOUR"]:
        db.session.commit()
        raise CodeError("Too many code requests. Please try again in an hour.", 429, retry_after=3600)

    code = f"{secrets.randbelow(1_000_000):06d}"     # a real code is only ever emailed when `sendable`
    db.session.execute(update(EmailOtp).where(EmailOtp.email == email, EmailOtp.is_used.is_(False)).values(is_used=True))  # only the newest code works
    row = EmailOtp(email=email, otp_hash=_hash(email, code, purpose), created_at=now, expires_at=now + timedelta(seconds=cfg["OTP_TTL_SECONDS"]),
                   attempts=0, is_used=False, ip_address=ip or None)
    db.session.add(row)
    db.session.commit()

    if sendable:
        try:
            send_now(email, *_email_parts(code, note))
        except MailUnavailable:
            current_app.logger.error("Verification code not sent: email is not configured (MAIL_MODE, MAIL_FROM and BREVO_API_KEY / RESEND_API_KEY / MAIL_SERVER).")
            db.session.delete(row); db.session.commit()
            raise CodeError(unavailable, 503) from None
        except Exception as exc:  # noqa: BLE001  (SMTP down, wrong login, timeout...)
            current_app.logger.error("Verification code email failed: %s", exc)
            db.session.delete(row); db.session.commit()   # a failed send must not use up the person's cooldown
            raise CodeError("We could not send the email just now. Please try again in a minute.", 503) from None
    return {"cooldown": cfg["OTP_RESEND_SECONDS"], "expires_in": cfg["OTP_TTL_SECONDS"]}


def check_code(email: str, code: str, purpose: str = "otp") -> None:
    """Check a 6 digit code for this address. Raises CodeError (already committed) when wrong, expired, used or locked.

    On success the code is used up and other waiting codes for the address are dropped, but NOT committed: the caller's next commit does it.
    """
    cfg = current_app.config
    now = utcnow()
    row = db.session.scalar(select(EmailOtp).where(EmailOtp.email == email, EmailOtp.is_used.is_(False))
                            .order_by(EmailOtp.created_at.desc()).limit(1).with_for_update())
    if row is None:
        raise CodeError(BAD_CODE)
    if row.expires_at <= now:
        row.is_used = True
        db.session.commit()
        raise CodeError(BAD_CODE, expired=True)
    if not hmac.compare_digest(row.otp_hash, _hash(email, code, purpose)):      # constant-time comparison
        row.attempts += 1
        if row.attempts >= cfg["OTP_MAX_ATTEMPTS"]:
            row.is_used = True
            db.session.commit()
            raise CodeError("Too many wrong attempts. Please ask for a new code.", locked=True)
        db.session.commit()
        raise CodeError(BAD_CODE)
    # right code: use it up, then drop any other waiting codes for this address
    row.is_used = True
    db.session.execute(delete(EmailOtp).where(EmailOtp.email == email, EmailOtp.id != row.id, EmailOtp.is_used.is_(False)))


@bp.post("/login/otp/send")
@limiter.limit(limits.limit("otp_send"))
def otp_send():
    if g.user is not None:
        return _fail("You are already signed in.", 409)
    email = normalize_email(v.strip_controls(str(_data().get("email", ""))))
    if not valid_email(email):
        return _fail("Enter a valid email address.", 422)
    user = db.session.scalar(select(User).where(func.lower(User.email) == email))
    try:
        info = issue_code(email, sendable=_may_get_code(user))
    except CodeError as exc:
        return _fail(exc.message, exc.status, **exc.extra)
    return jsonify(ok=True, message=GENERIC_SENT, **info)


def _name_from_email(email: str) -> str:
    local = re.sub(r"[^A-Za-z\u00C0-\u024F\u0B80-\u0BFF ]+", " ", email.split("@")[0])
    name = " ".join(local.split()).title()[:60]
    return name if len(name) >= 2 else "Customer"


@bp.post("/login/otp/verify")
@limiter.limit(limits.limit("otp_verify"))
def otp_verify():
    if g.user is not None:
        return _fail("You are already signed in.", 409)
    data = _data()
    email = normalize_email(v.strip_controls(str(data.get("email", ""))))
    code = re.sub(r"\D", "", str(data.get("code", "")))
    if not valid_email(email) or len(code) != 6:
        return _fail("Enter the 6 digit code from your email.", 422)

    now = utcnow()
    try:
        check_code(email, code)
    except CodeError as exc:
        return _fail(exc.message, exc.status, **exc.extra)

    user = db.session.scalar(select(User).where(func.lower(User.email) == email))
    created = False
    if user is None:
        user = User(email=email, name=_name_from_email(email), role="user", password_hash=hash_password(secrets.token_urlsafe(32)),
                    referral_code="RR" + secrets.token_hex(4).upper(), email_verified_at=now)
        db.session.add(user)
        try:
            db.session.flush()
            created = True
            audit("auth.register", entity_id=user.id, actor_id=user.id, after={"via": "email_otp"})
        except IntegrityError:      # two tabs created the same account at once
            db.session.rollback()
            user = db.session.scalar(select(User).where(func.lower(User.email) == email))
            if user is None:
                return _fail("We could not sign you in. Please try again.", 500)
    if not _may_get_code(user):      # staff, blocked or deleted: never signed in through this route
        db.session.commit()
        return _fail(BAD_CODE)
    if user.email_verified_at is None:
        user.email_verified_at = now
    user.last_login_at = now
    audit("auth.otp_login", entity_id=user.id, actor_id=user.id)
    login_user(user)     # new session, merges the guest cart, commits

    nxt = safe_next(str(data.get("next") or ""), "/")
    if nxt.startswith(("/owner", "/admin")):
        nxt = "/"
    if not created:   # new accounts get the name step first; returning customers see this on the page they land on
        flash(f"Welcome back, {user.name.split()[0] if user.name else 'there'}!", "success")
    return jsonify(ok=True, redirect=nxt, new_user=created, name=user.name if created else "")


@bp.post("/login/otp/name")
def otp_name():
    """Optional step after a brand-new account signs in: replace the name guessed from the email."""
    if g.user is None or g.user.role != "user":
        return _fail("Please sign in first.", 401)
    errors: dict = {}
    name = v.person_name(str(_data().get("name", "")), "name", errors, label="Your name")
    if errors:
        return _fail(errors["name"], 422)
    g.user.name = name
    db.session.commit()
    return jsonify(ok=True)
