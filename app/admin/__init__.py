from flask import Blueprint

from ..auth.decorators import roles_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
@roles_required("admin")
def _guard():
    """Every route in this blueprint is admin-only, including ones added in later steps."""


# Importing the modules registers their routes on `bp`.
from . import account, dashboard, categories, products, bulk, banners, users, audit, reviews, content, offers, coupons, combos, bundles, inbox  # noqa: E402,F401
