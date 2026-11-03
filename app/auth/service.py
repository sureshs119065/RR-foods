"""Sign-in logic. One place for password checks, lockout, sessions and audit entries."""
import hashlib
from datetime import timedelta
from urllib.parse import urlparse

from flask import current_app, g, request, session
from sqlalchemy import func, select

from ..extensions import db
from ..models import AuditLog, User
from ..models.base import utcnow
from ..security import hash_password, needs_rehash, verify_password

# Each portal has its own login page and accepts only its own role.
PORTALS = {
    "user": {"role": "user", "login": "/login", "home": "/account", "label": "Customer"},
    "owner": {"role": "owner", "login": "/owner/login", "home": "/owner/", "label": "Owner"},
    "admin": {"role": "admin", "login": "/admin/login", "home": "/admin/", "label": "Admin"},
}
STAFF_ROLES = ("owner", "admin")

# A real argon2 hash so a wrong email takes as long as a wrong password (no account-guessing by timing).
_DUMMY_HASH = hash_password("not-a-real-password")


def audit(action: str, entity_type: str = "user", entity_id=None, actor_id=None, before=None, after=None) -> None:
    db.session.add(AuditLog(
        actor_id=actor_id, action=action, entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=before, after=after, ip_address=(request.remote_addr or "")[:45] if request else None,
    ))


def session_token(user: User) -> str:
    """Changes whenever the password changes, which signs out every other device."""
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:24]


def safe_next(target: str | None, fallback: str) -> str:
    """Only allow same-site relative paths (blocks open-redirect tricks like //evil.com or https://evil.com)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return fallback
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return fallback
    return target


def is_locked(user: User) -> bool:
    return bool(user.locked_until and user.locked_until > utcnow())


def authenticate(portal: str, email: str, password: str) -> tuple[User | None, str | None]:
    """Returns (user, None) on success or (None, message). The message never says which part was wrong."""
    generic = "Incorrect email or password."
    cfg = current_app.config
    user = db.session.scalar(select(User).where(func.lower(User.email) == email, User.is_deleted.is_(False)))

    if user is None:
        verify_password(_DUMMY_HASH, password)
        return None, generic

    if is_locked(user):
        verify_password(_DUMMY_HASH, password)
        minutes = max(1, int((user.locked_until - utcnow()).total_seconds() // 60) + 1)
        return None, f"Too many attempts. Try again in about {minutes} minutes."

    ok = verify_password(user.password_hash, password)
    right_portal = user.role == PORTALS[portal]["role"]

    if not ok or not right_portal:
        if not ok:  # count only real wrong passwords, not a right password on the wrong portal
            user.failed_login_count += 1
            if user.failed_login_count >= cfg["MAX_FAILED_LOGINS"]:
                user.locked_until = utcnow() + timedelta(minutes=cfg["LOCKOUT_MINUTES"])
                user.failed_login_count = 0
                audit("auth.locked", entity_id=user.id, actor_id=user.id)
        if user.role in STAFF_ROLES or portal in ("owner", "admin"):
            audit("auth.failed_staff_login", entity_id=user.id, actor_id=user.id, after={"portal": portal})
        db.session.commit()
        return None, generic

    if user.is_blocked:
        db.session.commit()
        return None, "This account has been blocked. Please contact the shop."

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    return user, None


def login_user(user: User) -> None:
    session.clear()  # new session on every sign-in (prevents session fixation)
    session["uid"] = user.id
    session["tok"] = session_token(user)
    session["seen"] = utcnow().timestamp()
    session.permanent = user.role == "user"  # staff sessions end when the browser closes
    audit("auth.login", entity_id=user.id, actor_id=user.id)
    db.session.commit()


def logout_user() -> None:
    uid = session.get("uid")
    if uid:
        audit("auth.logout", entity_id=uid, actor_id=uid)
        db.session.commit()
    session.clear()


def load_current_user() -> None:
    """Runs before every request. Sets g.user, or None when the session is missing, expired, or the account was blocked."""
    g.user = None
    uid = session.get("uid")
    if not uid:
        return
    user = db.session.get(User, uid)
    now = utcnow().timestamp()
    idle_limit = current_app.config["STAFF_IDLE_MINUTES"] * 60

    invalid = (
        user is None or user.is_deleted or user.is_blocked
        or session.get("tok") != session_token(user)
        or (user.role in STAFF_ROLES and now - session.get("seen", 0) > idle_limit)
    )
    if invalid:
        session.clear()
        return
    session["seen"] = now
    g.user = user
