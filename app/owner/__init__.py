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
    from ..models import Order

    return {"pending_count": db.session.scalar(select(func.count(Order.id)).where(Order.status == "placed")) or 0}


# Importing the modules registers their routes on `bp`.
from . import account, dashboard, inventory, orders, questions, inbox  # noqa: E402,F401
