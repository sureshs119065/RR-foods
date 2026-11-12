from datetime import date, datetime, time, timedelta, timezone

from flask import Response, jsonify, render_template, request, url_for
from sqlalchemy import func, select

from ..admin.helpers import shop_tz
from ..extensions import db
from ..models import InventoryBatch, Order, OrderItem, Product
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

    today_local = utcnow().astimezone(shop_tz()).date()
    expiry_cutoff = today_local + timedelta(days=30)
    expiring_batches = db.session.scalars(
        select(InventoryBatch).where(InventoryBatch.expiry_date.is_not(None),
            InventoryBatch.expiry_date >= today_local, InventoryBatch.expiry_date <= expiry_cutoff,
            InventoryBatch.quantity > 0).order_by(InventoryBatch.expiry_date).limit(8)
    ).all()
    out_items = db.session.scalars(select(Product).where(live, Product.stock_qty == 0).order_by(Product.name).limit(8)).all()
    sales_30_start = datetime.combine(today_local - timedelta(days=30), time.min, tzinfo=shop_tz()).astimezone(timezone.utc)
    sold_rows = db.session.execute(
        select(OrderItem.product_id, func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.created_at >= sales_30_start, Order.status.in_(("confirmed", "packed", "shipped", "out_for_delivery", "delivered")))
        .group_by(OrderItem.product_id)
    ).all()
    sold_per_day = {pid: float(qty or 0) / 30 for pid, qty in sold_rows}
    stock_estimates = []
    for product in db.session.scalars(select(Product).where(live, Product.stock_qty > 0).order_by(Product.stock_qty)).all():
        rate = sold_per_day.get(product.id, 0)
        if rate > 0:
            stock_estimates.append({"product": product, "days": round(product.stock_qty / rate, 1)})
    stock_estimates.sort(key=lambda item: item["days"])

    sales_analytics = build_sales_analytics(
        request.args.get("range"), request.args.get("start_date"), request.args.get("end_date"), shop_tz()
    )
    return render_template("owner/dashboard.html", orders_today=orders_today, pending=pending, pending_total=pending_total,
                           to_ship=to_ship, low_total=low_total, low_items=low_items,
                           sales_analytics=sales_analytics, analytics_refresh_url=url_for("owner.analytics_data"), now_utc=utcnow(),
                           expiring_batches=expiring_batches, out_items=out_items, stock_estimates=stock_estimates[:8])


@bp.get("/analytics-data")
def analytics_data():
    """Fresh single-store metrics for the owner dashboard background refresh."""
    return jsonify(build_sales_analytics(
        request.args.get("range"), request.args.get("start_date"), request.args.get("end_date"), shop_tz()
    ))


@bp.get("/analytics.csv")
def analytics_csv():
    """Export the selected sales period as a simple CSV (owner-only blueprint)."""
    import csv
    import io
    data = build_sales_analytics(request.args.get("range"), request.args.get("start_date"), request.args.get("end_date"), shop_tz())
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Metric", "Value"])
    for key, value in (("Range", data["range_label"]), ("Total sales", data["total_sales"]),
                       ("Orders", data["total_orders"]), ("Average order value", data["average_order_value"]),
                       ("Repeat customer rate (%)", data["repeat_customer_rate"])):
        writer.writerow([key, value])
    writer.writerow([]); writer.writerow(["Product", "Sales value"])
    for item in data["top_products"]: writer.writerow([item["label"], item["value"]])
    writer.writerow([]); writer.writerow(["Coupon", "Orders", "Discount", "Sales"])
    for item in data["coupon_performance"]: writer.writerow([item["code"], item["orders"], item["discount"], item["sales"]])
    writer.writerow([]); writer.writerow(["Pincode", "Sales"])
    for item in data["orders_by_pincode"]: writer.writerow([item["label"], item["value"]])
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=rr-foods-sales-insights.csv"})
