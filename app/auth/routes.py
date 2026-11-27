from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from .. import ratelimits as limits
from .. import validation as v
from ..extensions import db, limiter
from ..models import User
from ..models.base import utcnow
from ..security import hash_password, verify_password
from .decorators import login_required
from .passwords import normalize_email, normalize_phone, password_problems, valid_email
from .service import PORTALS, audit, authenticate, login_user, logout_user, safe_next, session_token

bp = Blueprint("auth", __name__)


def _rate_limit():
    """Sign-in limit: per minute (LOGIN_RATE_LIMIT) plus an hourly cap, per IP."""
    from flask import current_app
    return f'{current_app.config["LOGIN_RATE_LIMIT"]};{limits.limit("login_hourly")()}'


def _login(portal: str):
    cfg = PORTALS[portal]
    if g.user is not None and g.user.role == cfg["role"]:
        return redirect(cfg["home"])
    email = ""
    error = None
    if request.method == "POST":
        email = normalize_email(v.strip_controls(request.form.get("email", "")))
        password = request.form.get("password", "")
        if not email or not password:
            error = "Enter your email and password."
        elif len(email) > v.MAX["email"] or len(password) > v.MAX["password"]:
            error = "Incorrect email or password."   # never hash a megabyte-long "password"
        else:
            user, error = authenticate(portal, email, password)
            if user:
                login_user(user)
                nxt = safe_next(request.args.get("next") or request.form.get("next"), cfg["home"])
                # a customer link must not send staff into the other portal and vice versa
                if portal != "user" and not nxt.startswith(f"/{portal}/"):
                    nxt = cfg["home"]
                if portal == "user" and nxt.startswith(("/owner", "/admin")):
                    nxt = cfg["home"]
                return redirect(nxt)
        status = 429 if error and error.startswith("Too many") else 401
        if portal == "user":   # wrong password on the customer page: show the code form with the password fallback open
            return render_template("auth/login_otp.html", portal=portal, cfg=cfg, email=email, error=error,
                                   next=request.args.get("next", "")), status
        return render_template("auth/login.html", portal=portal, cfg=cfg, email=email, error=error,
                               next=request.args.get("next", "")), status
    if portal == "user":   # customers: email code first (the password form stays on the same page as a fallback)
        return render_template("auth/login_otp.html", portal=portal, cfg=cfg, email="", error=None, next=request.args.get("next", ""))
    return render_template("auth/login.html", portal=portal, cfg=cfg, email=email, error=None, next=request.args.get("next", ""))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(_rate_limit, methods=["POST"])
def login():
    return _login("user")


@bp.route("/owner/login", methods=["GET", "POST"])
@limiter.limit(_rate_limit, methods=["POST"])
def owner_login():
    return _login("owner")


@bp.route("/admin/login", methods=["GET", "POST"])
@limiter.limit(_rate_limit, methods=["POST"])
def admin_login():
    return _login("admin")


@bp.post("/logout")
def logout():
    role = g.user.role if g.user else "user"
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(PORTALS.get(role, PORTALS["user"])["login"])


@bp.route("/account")
@login_required("user")
def account():
    if g.user.role != "user":
        return redirect(PORTALS[g.user.role]["home"])
    from sqlalchemy import func, select
    from sqlalchemy.orm import selectinload
    from ..models import Address, Notification, Order, WishlistItem
    total_orders = db.session.scalar(select(func.count(Order.id)).where(Order.user_id == g.user.id, Order.status != "pending_whatsapp")) or 0
    active_orders = db.session.scalar(select(func.count(Order.id)).where(Order.user_id == g.user.id,
        Order.status.in_(("placed", "confirmed", "packed", "shipped", "out_for_delivery")))) or 0
    wishlist_count = db.session.scalar(select(func.count(WishlistItem.id)).where(WishlistItem.user_id == g.user.id)) or 0
    unread_count = db.session.scalar(select(func.count(Notification.id)).where(Notification.user_id == g.user.id,
        Notification.channel == "in_app", Notification.is_read.is_(False))) or 0
    recent_orders = db.session.scalars(select(Order).where(Order.user_id == g.user.id)
        .options(selectinload(Order.items)).order_by(Order.created_at.desc(), Order.id.desc()).limit(3)).all()
    default_address = db.session.scalar(select(Address).where(Address.user_id == g.user.id)
        .order_by(Address.is_default.desc(), Address.id.desc()).limit(1))
    recent_notifications = db.session.scalars(select(Notification).where(Notification.user_id == g.user.id,
        Notification.channel == "in_app").order_by(Notification.created_at.desc(), Notification.id.desc()).limit(3)).all()
    return render_template("account/index.html", total_orders=total_orders, active_orders=active_orders,
        wishlist_count=wishlist_count, unread_count=unread_count, recent_orders=recent_orders,
        default_address=default_address, recent_notifications=recent_notifications)


@bp.route("/account/password", methods=["GET", "POST"])
@login_required("user")
def change_password():
    return _change_password("account/password.html", "/account")


def _mask_email(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    return (local[:2] + "*" * min(5, max(2, len(local) - 2)) if len(local) > 2 else local[:1] + "**") + "@" + domain


def _finish_password_change(new: str, done_url: str, via: str):
    g.user.password_hash = hash_password(new)
    session["tok"] = session_token(g.user)  # keeps this device signed in, signs out all others
    audit("auth.password_changed", entity_id=g.user.id, actor_id=g.user.id, after={"via": via})
    db.session.commit()
    flash("Password changed. Other devices were signed out.", "success")
    return redirect(done_url)


def _change_password(template: str, done_url: str):
    """Change password for a signed-in customer, admin or owner.

    Two ways to prove it is you: the current password, or (when it is forgotten) a 6 digit code emailed to the account's OWN address.
    The code is only ever sent to the signed-in account's email, never to an address typed in, and it uses the shared code engine in
    otp.py with its own purpose ("pwchange"), so it can never be used to sign in or to create an account.
    """
    from flask import current_app
    from .otp import CodeError, check_code, issue_code   # imported here: otp.py imports this module

    errors: dict[str, str] = {}
    ctx = {"errors": errors, "mode": "password", "masked_email": _mask_email(g.user.email), "notice": None}
    if request.method == "GET":
        if request.args.get("forgot"):
            ctx["mode"] = "otp_request"
        return render_template(template, **ctx)

    action = request.form.get("action", "password")
    email = normalize_email(g.user.email)

    if action == "send_code":
        try:
            info = issue_code(email, purpose="pwchange", note="Use it to change your password.",
                              unavailable="Email codes are not available right now. Please use your current password.")
        except CodeError as exc:
            errors["code"] = exc.message
            # a 429 for the short resend wait means a code was just sent, so stay on the "enter code" step
            waiting = exc.status == 429 and exc.extra.get("retry_after", 3600) <= current_app.config["OTP_RESEND_SECONDS"]
            ctx["mode"] = "otp_verify" if waiting else "otp_request"
            return render_template(template, **ctx), exc.status
        audit("auth.password_code_sent", entity_id=g.user.id, actor_id=g.user.id)
        db.session.commit()
        ctx["mode"] = "otp_verify"
        ctx["notice"] = f"We sent a 6 digit code to {ctx['masked_email']}. It is valid for {info['expires_in'] // 60} minutes. Check your spam folder too."
        return render_template(template, **ctx)

    new = request.form.get("new", "")
    confirm = request.form.get("confirm", "")

    if action == "change_with_code":
        ctx["mode"] = "otp_verify"
        import re
        code = re.sub(r"\D", "", request.form.get("code", ""))
        if len(code) != 6:
            errors["code"] = "Enter the 6 digit code from your email."
        problems = password_problems(new, g.user.email, g.user.name)
        if problems:
            errors["new"] = " ".join(problems)
        elif len(new) <= v.MAX["password"] and verify_password(g.user.password_hash, new):
            errors["new"] = "Choose a password different from the current one."
        elif new != confirm:
            errors["confirm"] = "The two passwords do not match."
        if not errors:
            try:
                check_code(email, code, "pwchange")
            except CodeError as exc:
                errors["code"] = exc.message
                if exc.extra.get("locked") or exc.extra.get("expired"):
                    ctx["mode"] = "otp_request"      # needs a fresh code
        if errors:
            return render_template(template, **ctx), 422
        return _finish_password_change(new, done_url, "email_code")

    # default: current password
    current = request.form.get("current", "")
    if len(current) > v.MAX["password"] or not verify_password(g.user.password_hash, current):
        errors["current"] = "Your current password is not correct."
    problems = password_problems(new, g.user.email, g.user.name)
    if problems:
        errors["new"] = " ".join(problems)
    elif new == current:
        errors["new"] = "Choose a password different from the current one."
    elif new != confirm:
        errors["confirm"] = "The two passwords do not match."
    if errors:
        return render_template(template, **ctx), 422
    return _finish_password_change(new, done_url, "current_password")


from . import recovery  # noqa: E402,F401  (forgot/reset routes)
from . import otp  # noqa: E402,F401  (customer email sign-in code routes)
from . import signup  # noqa: E402,F401  (create account + email verification code routes)
