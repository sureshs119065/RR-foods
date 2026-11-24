"""Create account, with the email address verified by a 6 digit code (OTP) before the account exists.

Flow
  1. /register           the form. Valid input does NOT create an account: a code is emailed and the details wait in the session.
  2. /register/verify    the person types the code. Only a correct code creates the account (email_verified_at is set) and signs them in.
  3. /register/resend    a new code, under the same cooldown and hourly caps as the login codes.

The code engine (hashing, 5 minute expiry, 5 guesses, resend cooldown, hourly caps) is the one in otp.py, used with purpose "signup" so a
login code can never complete a sign-up and the other way round. The password is hashed before it is put in the session, never kept as typed.
Owner and admin accounts are never created here: the role is always "user" and a "role" field in the request is ignored.
"""
import re
import secrets
from datetime import timedelta

from flask import flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .. import ratelimits as limits
from .. import validation as v
from ..extensions import db, limiter
from ..models import User
from ..models.base import utcnow
from ..security import hash_password
from . import otp
from .passwords import normalize_email, password_problems, valid_email
from .routes import bp
from .service import PORTALS, audit, login_user

PURPOSE = "signup"
SESSION_KEY = "signup"
PENDING_SECONDS = 30 * 60      # how long a half-finished sign-up is remembered (a code itself lives OTP_TTL_SECONDS)
EMAIL_NOTE = "Enter it on the sign-up page to verify your email and finish creating your account."
MAIL_DOWN = "We cannot send verification emails right now. Please try again a little later."


# ----------------------------------------------------------------- the half-finished sign-up kept in the session
def _pending() -> dict | None:
    data = session.get(SESSION_KEY)
    if not isinstance(data, dict) or not all(k in data for k in ("name", "email", "pw", "t")):
        return None
    if utcnow().timestamp() - data["t"] > PENDING_SECONDS:
        session.pop(SESSION_KEY, None)
        return None
    return data


def _remember(name: str, email: str, phone: str | None, password_hash: str, sent: bool) -> dict:
    now = utcnow().timestamp()
    old = session.get(SESSION_KEY) if isinstance(session.get(SESSION_KEY), dict) else {}
    data = {"name": name, "email": email, "phone": phone, "pw": password_hash, "t": now,
            "sent": now if sent else (old.get("sent", 0) if old.get("email") == email else 0)}
    session[SESSION_KEY] = data
    return data


def _resend_in(pending: dict) -> int:
    """Seconds until another code may be asked for (the page counts this down)."""
    from flask import current_app
    return max(0, current_app.config["OTP_RESEND_SECONDS"] - int(utcnow().timestamp() - pending.get("sent", 0)))


def _verify_page(pending: dict, error: str | None = None, status: int = 200, new_code_needed: bool = False):
    return render_template("auth/register_verify.html", email=pending["email"], error=error, resend_in=_resend_in(pending),
                           new_code_needed=new_code_needed), status


def _email_taken(email: str) -> bool:
    return bool(db.session.scalar(select(User.id).where(func.lower(User.email) == email)))


# ----------------------------------------------------------------- step 1: the form
@bp.route("/register", methods=["GET", "POST"])
@limiter.limit(limits.limit("register"), methods=["POST"])
def register():
    if g.user is not None:
        return redirect(PORTALS[g.user.role]["home"])
    errors: dict[str, str] = {}
    banner = None
    pending = _pending()
    form = {"name": pending["name"], "email": pending["email"], "phone": pending["phone"] or ""} if pending else {"name": "", "email": "", "phone": ""}
    if request.method == "POST":
        # Only these fields are read. A "role" field in the request is ignored, so nobody can sign up as admin.
        name = v.one_line(request.form.get("name", ""))
        email = normalize_email(v.strip_controls(request.form.get("email", "")))
        phone_raw = v.strip_controls(request.form.get("phone", ""))[:v.MAX["phone_raw"]]
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        form = {"name": name, "email": email, "phone": phone_raw}

        v.person_name(name, "name", errors, label="Your name")
        if "name" in errors and not 2 <= len(name) <= v.MAX["name"]:
            errors["name"] = "Enter your name (2 to 120 characters)."
        if not valid_email(email) or len(email) > v.MAX["email"]:
            errors["email"] = "Enter a valid email address."
        phone_errors: dict = {}
        phone = v.phone(phone_raw, "phone", phone_errors, required=False) or None
        if phone_errors:
            errors["phone"] = "Enter a 10 digit mobile number, or leave it empty."
        problems = password_problems(password, email, name)
        if problems:
            errors["password"] = " ".join(problems)
        elif password != confirm:
            errors["confirm"] = "The two passwords do not match."
        if "email" not in errors and _email_taken(email):
            errors["email"] = "An account with this email already exists. Try signing in."

        if not errors:
            password_hash = hash_password(password)
            try:
                otp.issue_code(email, purpose=PURPOSE, note=EMAIL_NOTE, unavailable=MAIL_DOWN)
            except otp.CodeError as exc:
                if exc.status == 429 and exc.extra.get("retry_after", 0) < 3600 and pending and pending["email"] == email:
                    # same address resubmitted a moment later (back button, double tap): the code already sent still works
                    _remember(name, email, phone, password_hash, sent=False)
                    flash("We already sent a code to this email a moment ago. Use that one, or ask for a new one in a few seconds.", "info")
                    return redirect(url_for("auth.register_verify"))
                banner = exc.message
                return render_template("auth/register.html", form=form, errors=errors, banner=banner), exc.status
            _remember(name, email, phone, password_hash, sent=True)
            return redirect(url_for("auth.register_verify"))
        return render_template("auth/register.html", form=form, errors=errors, banner=None), 422
    return render_template("auth/register.html", form=form, errors=errors, banner=None)


# ----------------------------------------------------------------- step 2: the code
@bp.route("/register/verify", methods=["GET", "POST"])
@limiter.limit(limits.limit("otp_verify"), methods=["POST"])
def register_verify():
    if g.user is not None:
        return redirect(PORTALS[g.user.role]["home"])
    pending = _pending()
    if pending is None:
        if request.method == "POST":
            flash("Your sign-up timed out. Please fill in the form again.", "info")
        return redirect(url_for("auth.register"))
    if request.method == "GET":
        return _verify_page(pending)

    code = re.sub(r"\D", "", request.form.get("code", "")[:32])
    if len(code) != 6:
        return _verify_page(pending, "Enter the 6 digit code from your email.", 422)
    try:
        otp.check_code(pending["email"], code, PURPOSE)
    except otp.CodeError as exc:
        return _verify_page(pending, exc.message, exc.status, new_code_needed=bool(exc.extra.get("locked") or exc.extra.get("expired")))

    # Right code: the email address is proven. Only now does the account exist.
    email = pending["email"]
    if _email_taken(email):      # someone else finished the same address while this page was open
        session.pop(SESSION_KEY, None)
        db.session.commit()
        flash("An account with this email already exists. Please sign in.", "info")
        return redirect(PORTALS["user"]["login"])
    now = utcnow()
    user = User(email=email, name=pending["name"], phone=pending["phone"], role="user", password_hash=pending["pw"],
                referral_code="RR" + secrets.token_hex(4).upper(), email_verified_at=now, last_login_at=now)
    db.session.add(user)
    try:
        db.session.flush()
    except IntegrityError:      # two tabs finished the same sign-up at once
        db.session.rollback()
        session.pop(SESSION_KEY, None)
        flash("An account with this email already exists. Please sign in.", "info")
        return redirect(PORTALS["user"]["login"])
    audit("auth.register", entity_id=user.id, actor_id=user.id, after={"via": "signup_otp"})
    login_user(user)     # new session (the pending sign-up is cleared with it), merges the guest cart, commits
    flash("Welcome! Your email is verified and your account is ready.", "success")
    return redirect("/account")


# ----------------------------------------------------------------- a new code
@bp.post("/register/resend")
@limiter.limit(limits.limit("otp_send"))
def register_resend():
    if g.user is not None:
        return redirect(PORTALS[g.user.role]["home"])
    pending = _pending()
    if pending is None:
        flash("Your sign-up timed out. Please fill in the form again.", "info")
        return redirect(url_for("auth.register"))
    try:
        otp.issue_code(pending["email"], purpose=PURPOSE, note=EMAIL_NOTE, unavailable=MAIL_DOWN)
    except otp.CodeError as exc:
        return _verify_page(pending, exc.message, exc.status)
    pending = _remember(pending["name"], pending["email"], pending["phone"], pending["pw"], sent=True)
    flash(f"We sent a new 6 digit code to {pending['email']}.", "success")
    return redirect(url_for("auth.register_verify"))
