from flask import Blueprint

from ..auth.decorators import roles_required

bp = Blueprint("owner", __name__, url_prefix="/owner")


@bp.before_request
@roles_required("owner")
def _guard():
    """Every route in this blueprint is owner-only, including ones added in later steps."""


@bp.context_processor
def _owner_menu():
    """Number of orders waiting for a decision, shown as a badge in the menu."""
    from sqlalchemy import func, select

    from ..extensions import db
    from ..models import Order, Product

    pending = db.session.scalar(select(func.count(Order.id)).where(Order.status == "placed")) or 0
    low_stock = db.session.scalar(select(func.count(Product.id)).where(
        Product.is_deleted.is_(False), Product.stock_qty <= Product.low_stock_threshold
    )) or 0
    return {"pending_count": pending, "low_stock_count": low_stock}


# Importing the modules registers their routes on `bp`.
from . import account, dashboard, inventory, orders, questions, inbox, delivery  # noqa: E402,F401
