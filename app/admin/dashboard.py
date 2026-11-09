from flask import jsonify, render_template, request, url_for
from sqlalchemy import func, select

from ..extensions import db
from ..models import Category, Coupon, HeaderBanner, Product, User
from ..admin.helpers import shop_tz
from ..services.analytics import build_sales_analytics
from . import bp


@bp.route("/")
def dashboard():
    count = lambda q: db.session.scalar(q) or 0
    live = (Product.is_deleted.is_(False))
    stats = {
        "products": count(select(func.count(Product.id)).where(live)),
        "active": count(select(func.count(Product.id)).where(live, Product.is_active.is_(True))),
        "low_stock": count(select(func.count(Product.id)).where(live, Product.stock_qty > 0, Product.stock_qty <= Product.low_stock_threshold)),
        "out_of_stock": count(select(func.count(Product.id)).where(live, Product.stock_qty == 0)),
        "archived": count(select(func.count(Product.id)).where(Product.is_deleted.is_(True))),
        "categories": count(select(func.count(Category.id)).where(Category.is_deleted.is_(False))),
        "banners": count(select(func.count(HeaderBanner.id)).where(HeaderBanner.is_active.is_(True))),
        "coupons": count(select(func.count(Coupon.id)).where(Coupon.is_active.is_(True))),
        "users": count(select(func.count(User.id)).where(User.role == "user", User.is_deleted.is_(False))),
    }
    sales_analytics = build_sales_analytics(
        request.args.get("range"), request.args.get("start_date"), request.args.get("end_date"), shop_tz()
    )
    return render_template("admin/dashboard.html", stats=stats, sales_analytics=sales_analytics,
                           analytics_refresh_url=url_for("admin.analytics_data"))


@bp.get("/analytics-data")
def analytics_data():
    """Fresh store-wide metrics for the dashboard's background refresh."""
    return jsonify(build_sales_analytics(
        request.args.get("range"), request.args.get("start_date"), request.args.get("end_date"), shop_tz()
    ))
