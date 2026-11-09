from flask import Blueprint, g, jsonify, redirect, request
from sqlalchemy import select

from ..auth.service import safe_next
from ..extensions import db

bp = Blueprint("shop", __name__)


@bp.app_context_processor
def _shop_helpers():
    """Callables, so pages that do not show the cart or the category menu (admin, owner) pay nothing for them."""
    from ..models import Category
    from ..services.cart import count_in_cart

    def cart_count() -> int:
        u = g.get("user")
        return count_in_cart(u.id) if u is not None and u.role == "user" else 0

    def nav_categories():
        return db.session.scalars(select(Category).where(Category.parent_id.is_(None), Category.is_deleted.is_(False), Category.is_active.is_(True))
                                  .order_by(Category.sort_order, Category.name).limit(14)).all()

    def announcements() -> list[str]:
        from flask import current_app
        return current_app.config.get("ANNOUNCEMENTS", [])

    from datetime import datetime
    return {"cart_count": cart_count, "nav_categories": nav_categories, "announcements": announcements, "current_year": datetime.now().year}


def wants_json() -> bool:
    return request.accept_mimetypes.best == "application/json"


def reply(ok: bool, message: str, fallback: str, code: int = 200, **extra):
    """JSON for the in-page buttons, flash + redirect for a plain form post (so everything works without JavaScript)."""
    if wants_json():
        return jsonify(ok=ok, message=message, **extra), code
    from flask import flash
    flash(message, "success" if ok else "error")
    return redirect(safe_next(request.form.get("next"), fallback))


from . import account, cart, catalog, checkout, engage, pwa, content, messages  # noqa: E402,F401
