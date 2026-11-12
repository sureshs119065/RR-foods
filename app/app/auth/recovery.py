"""Forgot password for customers. Staff accounts are reset by an admin (Admin > Users), never by email.

The link holds a signed, time-limited token that also carries a fingerprint of the current password. Changing the password changes the
fingerprint, so the link works once and dies with any other password change. The same message is shown whether or not the email exists.
"""
from flask import current_app, flash, g, redirect, render_template, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select

from ..extensions import db, limiter
from ..models import User
from ..security import hash_password
from ..services.mailer import queue_email
from .passwords import normalize_email, password_problems, valid_email
from .routes import _rate_limit, bp
from .service import audit, session_token

MAX_AGE = 3600
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


@bp.route("/forgot", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def forgot():
    if g.user is not None:
        return redirect("/account")
    sent = False
    error = None
    if request.method == "POST":
        email = normalize_email(request.form.get("email", ""))
        if not valid_email(email):
            error = "Enter a valid email address."
        else:
            user = db.session.scalar(select(User).where(func.lower(User.email) == email, User.role == "user"))
            if user is not None and not user.is_deleted and not user.is_blocked:
                queue_email(user.id, "password_reset", "Reset your RR FOODS password",
                            "Someone asked to reset your password. Open the link within 1 hour to choose a new one. If this was not you, ignore this email.",
                            link=f"/reset/{make_token(user)}")
                audit("auth.reset_requested", entity_id=user.id, actor_id=user.id)
                db.session.commit()
            sent = True  # same answer for unknown emails
    return render_template("auth/forgot.html", sent=sent, error=error), (422 if error else 200)


@bp.route("/reset/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
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
