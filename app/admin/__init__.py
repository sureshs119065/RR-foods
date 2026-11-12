from flask import Blueprint

from ..auth.decorators import roles_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
@roles_required("admin")
def _guard():
    """Every route in this blueprint is admin-only, including ones added in later steps."""


# Importing the modules registers their routes on `bp`.
from . import account, dashboard, categories, products, bulk, banners, users, audit, reviews, content, offers, coupons, combos, bundles, inbox, operations  # noqa: E402,F401

@bp.context_processor
def _admin_alert_counts():
    from sqlalchemy import func, select
    from ..extensions import db
    from ..models import Notification
    from flask import g
    unread = 0
    if getattr(g, "user", None) is not None:
        unread = db.session.scalar(select(func.count(Notification.id)).where(
            Notification.user_id == g.user.id, Notification.channel == "in_app", Notification.is_read.is_(False))) or 0
    return {"admin_unread_count": unread}
