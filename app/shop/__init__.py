from flask import Blueprint, g, jsonify, redirect, request
from sqlalchemy import select

from ..auth.service import safe_next
from ..extensions import db

bp = Blueprint("shop", __name__)


@bp.app_context_processor
def _shop_helpers():
    """Callables, so pages that do not show the cart or the category menu (admin, owner) pay nothing for them."""
    from ..models import Category
    from ..services.cart import cart_owner, count_in_cart

    def cart_count() -> int:
        return count_in_cart(cart_owner())  # signed-in customer, or the guest cookie cart; 0 for staff / no cart

    def nav_categories():
        from ..services.storefront import top_categories
        return top_categories()  # cached per worker for HOME_CACHE_SECONDS (services/home_cache.py)

    def announcements() -> list[str]:
        from flask import current_app
        return current_app.config.get("ANNOUNCEMENTS", [])

    def whatsapp_link(text: str = "") -> str | None:
        """wa.me link to the shop's WhatsApp (None when no number is configured), for the floating button and the home strip."""
        from ..services import whatsapp as wa
        return wa.link(wa.owner_number(), text)

    from datetime import datetime
    return {"whatsapp_link": whatsapp_link, "cart_count": cart_count, "nav_categories": nav_categories, "announcements": announcements, "current_year": datetime.now().year}


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
