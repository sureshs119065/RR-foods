from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from ..extensions import db, limiter
from ..models import User
from ..models.base import utcnow
from ..security import hash_password, verify_password
from .decorators import login_required
from .passwords import normalize_email, normalize_phone, password_problems, valid_email
from .service import PORTALS, audit, authenticate, login_user, logout_user, safe_next, session_token

bp = Blueprint("auth", __name__)


def _rate_limit():
    from flask import current_app
    return current_app.config["LOGIN_RATE_LIMIT"]


def _login(portal: str):
    cfg = PORTALS[portal]
    if g.user is not None and g.user.role == cfg["role"]:
        return redirect(cfg["home"])
    email = ""
    error = None
    if request.method == "POST":
        email = normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        if not email or not password:
            error = "Enter your email and password."
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
        return render_template("auth/login.html", portal=portal, cfg=cfg, email=email, error=error,
                               next=request.args.get("next", "")), status
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


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit(_rate_limit, methods=["POST"])
def register():
    if g.user is not None:
        return redirect(PORTALS[g.user.role]["home"])
    form = {"name": "", "email": "", "phone": ""}
    errors: dict[str, str] = {}
    if request.method == "POST":
        # Only these fields are read. A "role" field in the request is ignored, so nobody can sign up as admin.
        name = " ".join(request.form.get("name", "").split())
        email = normalize_email(request.form.get("email", ""))
        phone_raw = request.form.get("phone", "")
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        form = {"name": name, "email": email, "phone": phone_raw}

        if len(name) < 2 or len(name) > 120:
            errors["name"] = "Enter your name (2 to 120 characters)."
        if not valid_email(email):
            errors["email"] = "Enter a valid email address."
        phone = normalize_phone(phone_raw)
        if phone == "":
            errors["phone"] = "Enter a 10 digit mobile number, or leave it empty."
        problems = password_problems(password, email, name)
        if problems:
            errors["password"] = " ".join(problems)
        elif password != confirm:
            errors["confirm"] = "The two passwords do not match."
        if "email" not in errors:
            from sqlalchemy import func, select
            if db.session.scalar(select(User.id).where(func.lower(User.email) == email)):
                errors["email"] = "An account with this email already exists. Try signing in."

        if not errors:
            user = User(email=email, name=name, phone=phone, role="user", password_hash=hash_password(password))
            db.session.add(user)
            db.session.flush()
            audit("auth.register", entity_id=user.id, actor_id=user.id)
            login_user(user)
            flash("Welcome! Your account is ready.", "success")
            return redirect("/account")
        return render_template("auth/register.html", form=form, errors=errors), 422
    return render_template("auth/register.html", form=form, errors=errors)


@bp.route("/account")
@login_required("user")
def account():
    if g.user.role != "user":
        return redirect(PORTALS[g.user.role]["home"])
    return render_template("account/index.html")


@bp.route("/account/password", methods=["GET", "POST"])
@login_required("user")
def change_password():
    return _change_password("account/password.html", "/account")


def _change_password(template: str, done_url: str):
    errors: dict[str, str] = {}
    if request.method == "POST":
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        confirm = request.form.get("confirm", "")
        if not verify_password(g.user.password_hash, current):
            errors["current"] = "Your current password is not correct."
        problems = password_problems(new, g.user.email, g.user.name)
        if problems:
            errors["new"] = " ".join(problems)
        elif new == current:
            errors["new"] = "Choose a password different from the current one."
        elif new != confirm:
            errors["confirm"] = "The two passwords do not match."
        if not errors:
            g.user.password_hash = hash_password(new)
            session["tok"] = session_token(g.user)  # keeps this device signed in, signs out all others
            audit("auth.password_changed", entity_id=g.user.id, actor_id=g.user.id)
            db.session.commit()
            flash("Password changed. Other devices were signed out.", "success")
            return redirect(done_url)
        return render_template(template, errors=errors), 422
    return render_template(template, errors=errors)

from . import recovery  # noqa: E402,F401  (forgot/reset routes)
