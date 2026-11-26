from datetime import date, datetime, time, timedelta, timezone

from flask import Response, jsonify, render_template, request, url_for
from sqlalchemy import func, select

from ..admin.csvio import safe_cell
from ..admin.helpers import shop_tz
from ..extensions import db
from ..models import InventoryBatch, Order, OrderItem, Product
from ..models.base import utcnow
from ..services.analytics import build_sales_analytics
from ..services.xlsx_export import INT, MIXED, MONEY, PERCENT, TEXT, XLSX_MIMETYPE, Sheet, Typed, build_workbook
from . import bp


def _start_of_today_utc() -> datetime:
    now_local = utcnow().astimezone(shop_tz())
    return datetime.combine(now_local.date(), time.min, tzinfo=shop_tz()).astimezone(timezone.utc)



@bp.route("/")
def dashboard():
    today = _start_of_today_utc()
    tomorrow = today + timedelta(days=1)
    count = lambda q: db.session.scalar(q) or 0

    orders_today = count(select(func.count(Order.id)).where(Order.created_at >= today, Order.created_at < tomorrow, Order.status != "pending_whatsapp"))
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


def _report_data():
    return build_sales_analytics(request.args.get("range"), request.args.get("start_date"), request.args.get("end_date"), shop_tz())


def _nice_day(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d %b %Y")
    except ValueError:
        return iso


def _summary_rows(data) -> list[tuple]:
    """(label, value, kind) for the Summary sheet. The date range comes first."""
    return [
        ("Date range", data["range_label"], TEXT),
        ("From", _nice_day(data["start_date"]), TEXT),
        ("To", _nice_day(data["end_date"]), TEXT),
        ("Total sales", data["total_sales"], MONEY),
        ("Orders", data["total_orders"], INT),
        ("Accepted orders", data["accepted_orders"], INT),
        ("Average order value", data["average_order_value"], MONEY),
        ("Products sold", data["products_sold"], INT),
        ("Unique customers", data["unique_customers"], INT),
        ("Repeat customers", data["repeat_customers"], INT),
        ("Repeat customer rate", data["repeat_customer_rate"], PERCENT),
    ]


@bp.get("/analytics.xlsx")
def analytics_xlsx():
    """The selected sales period as a styled Excel file: Summary (with the date range), Top products, Coupons, Pincodes."""
    data = _report_data()
    sheets = [
        Sheet("Summary", ["Metric", "Value"], [TEXT, MIXED], [[label, Typed(value, kind)] for label, value, kind in _summary_rows(data)]),
        Sheet("Top products", ["Rank", "Product", "Sales"], [INT, TEXT, MONEY],
              [[n, item["label"], item["value"]] for n, item in enumerate(data["top_products"], start=1)]),
        Sheet("Coupons", ["Coupon", "Orders", "Discount", "Sales"], [TEXT, INT, MONEY, MONEY],
              [[c["code"], c["orders"], c["discount"], c["sales"]] for c in data["coupon_performance"]]),
        Sheet("Pincodes", ["Pincode", "Sales"], [TEXT, MONEY],
              [[item["label"], item["value"]] for item in data["orders_by_pincode"]]),
    ]
    return Response(build_workbook(sheets, clean=safe_cell), mimetype=XLSX_MIMETYPE, headers={
        "Content-Disposition": "attachment; filename=rr-foods-sales-report.xlsx", "Cache-Control": "no-store"})


@bp.get("/analytics.csv")
def analytics_csv():
    """The same report as one tidy table (Section, Item, Value, Orders, Discount): easy to filter or pivot. UTF-8 with a BOM."""
    import csv
    import io
    data = _report_data()
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["Section", "Item", "Value", "Orders", "Discount"])
    rows = [["Summary", label, value, "", ""] for label, value, _kind in _summary_rows(data)]
    rows += [["Top products", item["label"], item["value"], "", ""] for item in data["top_products"]]
    rows += [["Coupons", c["code"], c["sales"], c["orders"], c["discount"]] for c in data["coupon_performance"]]
    rows += [["Pincodes", item["label"], item["value"], "", ""] for item in data["orders_by_pincode"]]
    for row in rows:
        writer.writerow([safe_cell(x) if isinstance(x, str) else x for x in row])
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=rr-foods-sales-insights.csv", "Cache-Control": "no-store"})
