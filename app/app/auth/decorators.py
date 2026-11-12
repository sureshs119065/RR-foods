from functools import wraps

from flask import abort, g, redirect, request, url_for

from .service import PORTALS


def _portal_for_role(role: str) -> str:
    return {"user": "user", "owner": "owner", "admin": "admin"}[role]


def login_required(portal: str = "user"):
    """Signed-in users only. Anonymous visitors go to the login page of the given portal."""

    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.get("user") is None:
                return redirect(f"{PORTALS[portal]['login']}?next={request.full_path.rstrip('?')}")
            return view(*args, **kwargs)

        return wrapped

    return deco


def roles_required(*roles: str):
    """Only the listed roles may enter. Anonymous: sent to that portal's login. Wrong role: 403 (no redirect loops)."""

    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = g.get("user")
            if user is None:
                portal = roles[0] if roles[0] in PORTALS else "user"
                return redirect(f"{PORTALS[portal]['login']}?next={request.full_path.rstrip('?')}")
            if user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return deco
