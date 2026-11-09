from datetime import datetime, time, timedelta, timezone

from flask import jsonify, render_template, request, url_for
from sqlalchemy import func, select

from ..admin.helpers import shop_tz
from ..extensions import db
from ..models import Order, Product
from ..models.base import utcnow
from ..services.analytics import build_sales_analytics
from . import bp


def _start_of_today_utc() -> datetime:
    now_local = utcnow().astimezone(shop_tz())
    return datetime.combine(now_local.date(), time.min, tzinfo=shop_tz()).astimezone(timezone.utc)



@bp.route("/")
def dashboard():
    today = _start_of_today_utc()
    tomorrow = today + timedelta(days=1)
    count = lambda q: db.session.scalar(q) or 0

    orders_today = count(select(func.count(Order.id)).where(Order.created_at >= today, Order.created_at < tomorrow))
    pending_q = select(Order).where(Order.status == "placed").order_by(Order.created_at.asc())
    pending = db.session.scalars(pending_q.limit(5)).all()
    pending_total = count(select(func.count(Order.id)).where(Order.status == "placed"))
    to_ship = count(select(func.count(Order.id)).where(Order.status.in_(("confirmed", "packed"))))

    live = Product.is_deleted.is_(False)
    low_filter = (live, Product.stock_qty <= Product.low_stock_threshold)
    low_total = count(select(func.count(Product.id)).where(*low_filter))
    low_items = db.session.scalars(select(Product).where(*low_filter).order_by(Product.stock_qty.asc(), Product.name).limit(8)).all()

    sales_analytics = build_sales_analytics(
        request.args.get("range"), request.args.get("start_date"), request.args.get("end_date"), shop_tz()
    )
    return render_template("owner/dashboard.html", orders_today=orders_today, pending=pending, pending_total=pending_total,
                           to_ship=to_ship, low_total=low_total, low_items=low_items,
                           sales_analytics=sales_analytics, analytics_refresh_url=url_for("owner.analytics_data"), now_utc=utcnow())


@bp.get("/analytics-data")
def analytics_data():
    """Fresh single-store metrics for the owner dashboard background refresh."""
    return jsonify(build_sales_analytics(
        request.args.get("range"), request.args.get("start_date"), request.args.get("end_date"), shop_tz()
    ))
