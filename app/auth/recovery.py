"""Forgot password for customers. Staff accounts are reset by an admin (Admin > Users), never by email.

Three steps:
1. POST /forgot          the customer enters their email. If it belongs to a customer account, a 6 digit code is emailed (the shared
                         engine in otp.py, purpose "reset": 5 minutes, 5 wrong guesses, resend wait and hourly caps). Unknown email: 404.
2. POST /forgot/verify   the customer types the code. A right code answers with the address of the change-password page.
3. GET/POST /reset/<token>  the change-password page. The token is signed, lasts 15 minutes and carries a fingerprint of the current
                         password, so it works once and dies with any other password change.

The pages post normally (works without JavaScript) and static/js/forgot.js calls the same URLs with JSON for the in-page steps.
"""
from flask import current_app, flash, g, jsonify, redirect, render_template, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select

import re

from .. import ratelimits as limits
from .. import validation as v
from ..extensions import db, limiter
from ..models import User
from ..security import hash_password
from .otp import CodeError, check_code, issue_code
from .passwords import normalize_email, password_problems, valid_email
from .routes import _rate_limit, bp
from .service import audit, session_token

MAX_AGE = 900   # 15 minutes
NOT_REGISTERED = "This email is not registered. Please check your email or sign up."
SENT = "We have sent a 6 digit code to your email."
PURPOSE = "reset"   # mixed into the stored code hash: a login or sign-up code can never be used here
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
        try:
            info = issue_code(email, purpose=PURPOSE, note="Use it to reset your password.",
                              unavailable="We could not send the code right now. Please try again later.")
        except CodeError as exc:   # resend wait, hourly cap, or mail not configured / down (already committed)
            return exc.status, {"success": False, "message": exc.message, **exc.extra}
        audit("auth.reset_requested", entity_id=user.id, actor_id=user.id)
        db.session.commit()
    except Exception:  # noqa: BLE001 - database or mail-queue failure: clear message, no stack trace to the visitor
        db.session.rollback()
        current_app.logger.exception("Forgot-password request failed")
        return 500, {"success": False, "message": "Something went wrong while sending the code. Please try again."}
    return 200, {"success": True, "message": SENT, **info}


def _wants_json() -> bool:
    return request.is_json or request.accept_mimetypes.best == "application/json"


def _page(step: str, email: str = "", error: str | None = None, status: int = 200, not_registered: bool = False, info: dict | None = None):
    return render_template("auth/forgot.html", step=step, email=email, error=error, not_registered=not_registered, info=info or {}), status


def _body() -> dict:
    data = request.get_json(silent=True) if request.is_json else None
    return data if isinstance(data, dict) else request.form.to_dict()


@bp.route("/forgot", methods=["GET", "POST"])
@limiter.limit(limits.limit("password_reset_request"), methods=["POST"])
@limiter.limit(limits.limit("password_reset_email"), methods=["POST"], key_func=limits.email_key)
def forgot():
    """Step 1: ask for the code. Step 2 is the code box on the same page (see /forgot/verify)."""
    if g.user is not None:
        return redirect("/account")
    if request.method == "GET":
        return _page("email")
    raw = str(_body().get("email", ""))[:255]
    status, body = _forgot_outcome(raw)
    if _wants_json():
        return jsonify(body), status
    if status == 200:
        return _page("code", email=normalize_email(raw), info=body)
    return _page("email", email=raw.strip(), error=body["message"], status=status, not_registered=status == 404)


@bp.post("/forgot/verify")
@limiter.limit(limits.limit("otp_verify"))
def forgot_verify():
    """Step 2: check the emailed code. A right code sends the customer to the change-password page (step 3)."""
    if g.user is not None:
        return redirect("/account")
    data = _body()
    raw = str(data.get("email", ""))[:255]
    email = normalize_email(v.strip_controls(raw))
    code = re.sub(r"\D", "", str(data.get("code", "")))

    def fail(message: str, status: int = 400, **extra):
        if _wants_json():
            return jsonify(success=False, ok=False, message=message, **extra), status
        return _page("code", email=email, error=message, status=status)

    if not valid_email(email) or len(code) != 6:
        return fail("Enter the 6 digit code from your email.", 422)
    try:
        check_code(email, code, PURPOSE)
    except CodeError as exc:
        return fail(exc.message, exc.status, **exc.extra)
    user = db.session.scalar(select(User).where(func.lower(User.email) == email, User.role == "user"))
    if user is None or user.is_deleted or user.is_blocked:     # never hand out a reset page for staff, blocked or deleted accounts
        db.session.commit()
        return fail("That code is incorrect or has expired. Check the code or ask for a new one.")
    audit("auth.reset_code_verified", entity_id=user.id, actor_id=user.id)
    db.session.commit()
    link = f"/reset/{make_token(user)}"
    if _wants_json():
        return jsonify(success=True, ok=True, redirect=link)
    return redirect(link)


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
