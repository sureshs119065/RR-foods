"""Forgot password for customers. Staff accounts are reset by an admin (Admin > Users), never by email.

The link holds a signed, time-limited token (15 minutes) that also carries a fingerprint of the current password. Changing the password
changes the fingerprint, so the link works once and dies with any other password change.

POST /forgot first checks that the email belongs to a customer account. Unknown email: nothing is sent and the answer is 404
"This email is not registered...". Known email: the reset link is queued and the answer is 200 "Reset link sent to your email.".
The form posts normally (works without JavaScript) and static/js/forgot.js calls the same URL with JSON for the in-page messages.
"""
from flask import current_app, flash, g, jsonify, redirect, render_template, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select

from .. import ratelimits as limits
from ..extensions import db, limiter
from ..models import User
from ..security import hash_password
from ..services.mailer import queue_email
from .passwords import normalize_email, password_problems, valid_email
from .routes import _rate_limit, bp
from .service import audit, session_token

MAX_AGE = 900   # 15 minutes
NOT_REGISTERED = "This email is not registered. Please check your email or sign up."
SENT = "Reset link sent to your email."
SALT = "password-reset"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def make_token(user: User) -> str:
    return _serializer().dumps({"u": user.id, "f": session_token(user)[:16]})


def user_from_token(token: str) -> User | None:
    try:
        data = _serializer().loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, data.get("u"))
    if user is None or user.role != "user" or user.is_deleted or user.is_blocked or session_token(user)[:16] != data.get("f"):
        return None
    return user


def _forgot_outcome(email_raw: str) -> tuple[int, dict]:
    """Decide the answer for one reset request. Returns (http status, json body). Sends nothing for an unknown email."""
    email = normalize_email(email_raw)
    if not email:
        return 422, {"success": False, "message": "Enter your email address."}
    if not valid_email(email):
        return 422, {"success": False, "message": "Enter a valid email address."}
    try:
        user = db.session.scalar(select(User).where(func.lower(User.email) == email, User.role == "user"))
        if user is None or user.is_deleted:
            return 404, {"success": False, "message": NOT_REGISTERED}
        if user.is_blocked:
            return 403, {"success": False, "message": "This account is unavailable. Please contact support."}
        queued = queue_email(user.id, "password_reset", "Reset your RR FOODS password",
                             "Someone asked to reset your password. Open the link within 15 minutes to choose a new one. If this was not you, ignore this email.",
                             link=f"/reset/{make_token(user)}")
        if not queued:   # mail switched off or not configured
            db.session.rollback()
            current_app.logger.error("Password reset email could not be queued (MAIL_MODE=%s)", current_app.config.get("MAIL_MODE"))
            return 500, {"success": False, "message": "We could not send the email right now. Please try again later."}
        audit("auth.reset_requested", entity_id=user.id, actor_id=user.id)
        db.session.commit()
    except Exception:  # noqa: BLE001 - database or mail-queue failure: clear message, no stack trace to the visitor
        db.session.rollback()
        current_app.logger.exception("Forgot-password request failed")
        return 500, {"success": False, "message": "Something went wrong while sending the reset link. Please try again."}
    return 200, {"success": True, "message": SENT}


def _wants_json() -> bool:
    return request.is_json or request.accept_mimetypes.best == "application/json"


@bp.route("/forgot", methods=["GET", "POST"])
@limiter.limit(limits.limit("password_reset_request"), methods=["POST"])
@limiter.limit(limits.limit("password_reset_email"), methods=["POST"], key_func=limits.email_key)
def forgot():
    if g.user is not None:
        return redirect("/account")
    if request.method == "GET":
        return render_template("auth/forgot.html", sent=False, error=None, not_registered=False)
    data = request.get_json(silent=True) if request.is_json else None
    raw = str((data or {}).get("email", "")) if isinstance(data, dict) else request.form.get("email", "")
    status, body = _forgot_outcome(raw[:255])
    if _wants_json():
        return jsonify(body), status
    ok = status == 200
    return render_template("auth/forgot.html", sent=ok, error=None if ok else body["message"], not_registered=status == 404), status


@bp.route("/reset/<token>", methods=["GET", "POST"])
@limiter.limit(limits.limit("password_reset"), methods=["POST"])
def reset(token):
    user = user_from_token(token)
    if user is None:
        return render_template("auth/reset.html", invalid=True, errors={}), 400
    errors: dict[str, str] = {}
    if request.method == "POST":
        new, confirm = request.form.get("new", ""), request.form.get("confirm", "")
        problems = password_problems(new, user.email, user.name)
        if problems:
            errors["new"] = " ".join(problems)
        elif new != confirm:
            errors["confirm"] = "The two passwords do not match."
        if not errors:
            user.password_hash = hash_password(new)
            user.locked_until = None
            audit("auth.password_reset", entity_id=user.id, actor_id=user.id)
            db.session.commit()
            flash("Password changed. Sign in with your new password.", "success")
            return redirect("/login")
        return render_template("auth/reset.html", invalid=False, errors=errors), 422
    return render_template("auth/reset.html", invalid=False, errors=errors)
