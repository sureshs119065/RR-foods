import secrets

from flask import abort, flash, g, make_response, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from ..auth.passwords import normalize_email, valid_email
from ..extensions import db
from ..models import User
from ..models.base import utcnow
from ..security import hash_password
from . import bp
from .helpers import clean, log, page_number

PER_PAGE = 25


@bp.route("/users")
def users():
    q = select(User).where(User.is_deleted.is_(False))
    role = request.args.get("role", "")
    if role in ("user", "owner", "admin"):
        q = q.where(User.role == role)
    state = request.args.get("state", "")
    if state == "blocked":
        q = q.where(User.is_blocked.is_(True))
    term = (request.args.get("q") or "").strip().lower()
    if term:
        like = f"%{term}%"
        q = q.where(or_(func.lower(User.name).like(like), func.lower(User.email).like(like), func.coalesce(User.phone, "").like(like)))
    page = db.paginate(q.order_by(User.created_at.desc(), User.id.desc()), page=page_number(), per_page=PER_PAGE, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("admin/users.html", page=page, args=args, now_utc=utcnow())


def _target(user_id: int) -> User:
    return db.session.get(User, user_id) or abort(404)


@bp.post("/users/<int:user_id>/block")
def user_block(user_id):
    user = _target(user_id)
    if user.id == g.user.id:
        flash("You cannot block your own account.", "error")
    else:
        user.is_blocked = True  # signed out on their next request (see auth.service.load_current_user)
        log("user.block", "user", user.id, after={"email": user.email, "role": user.role})
        db.session.commit()
        flash(f"{user.email} is blocked and has been signed out.", "success")
    return redirect(request.referrer or url_for("admin.users"))


@bp.post("/users/<int:user_id>/unblock")
def user_unblock(user_id):
    user = _target(user_id)
    user.is_blocked = False
    user.failed_login_count, user.locked_until = 0, None
    log("user.unblock", "user", user.id, after={"email": user.email})
    db.session.commit()
    flash(f"{user.email} can sign in again.", "success")
    return redirect(request.referrer or url_for("admin.users"))


def _temp_password_page(user: User, title: str, password: str):
    """Shows a one-time password. Never cached, never put in the URL or the flash message."""
    resp = make_response(render_template("admin/temp_password.html", target=user, title=title, password=password))
    resp.headers["Cache-Control"] = "no-store"
    return resp


def new_temp_password() -> str:
    return secrets.token_urlsafe(9) + "7a"  # letters + digits so it passes the password rules


@bp.post("/users/<int:user_id>/reset-password")
def user_reset_password(user_id):
    user = _target(user_id)
    if user.id == g.user.id:
        flash("Use “Change password” for your own account.", "error")
        return redirect(url_for("admin.users"))
    password = new_temp_password()
    user.password_hash = hash_password(password)  # also signs the user out everywhere (session token changes)
    user.failed_login_count, user.locked_until = 0, None
    log("user.reset_password", "user", user.id, after={"email": user.email})
    db.session.commit()
    return _temp_password_page(user, "Password reset", password)


@bp.route("/users/new-owner", methods=["GET", "POST"])
def owner_new():
    errors: dict[str, str] = {}
    f = {"name": "", "email": ""}
    if request.method == "POST":
        name = clean(request.form.get("name"), 120)
        email = normalize_email(request.form.get("email"))
        f = {"name": name, "email": email}
        if len(name) < 2:
            errors["name"] = "Enter the owner's name."
        if not valid_email(email):
            errors["email"] = "Enter a valid email address."
        elif db.session.scalar(select(User.id).where(func.lower(User.email) == email)):
            errors["email"] = "An account with this email already exists."
        if not errors:
            password = new_temp_password()
            user = User(email=email, name=name, role="owner", password_hash=hash_password(password), email_verified_at=utcnow())
            db.session.add(user)
            db.session.flush()
            log("user.create_owner", "user", user.id, after={"email": email})
            db.session.commit()
            return _temp_password_page(user, "Owner account created", password)
        return render_template("admin/owner_form.html", f=f, errors=errors), 422
    return render_template("admin/owner_form.html", f=f, errors=errors)
