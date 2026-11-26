"""Owner downloads: orders and stock (Excel and CSV).

Every route sits on the owner blueprint, so the owner-only guard in owner/__init__.py covers it (an admin or a customer is refused).
Both exports use the SAME filters as the on-screen lists. The orders file leaves out the customer's e-mail address: the owner only
needs a name, phone and delivery area to fulfil an order. Each export is written to the audit log.
"""
from datetime import datetime

from flask import Response, g, request
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from ..admin.helpers import shop_tz
from ..auth.service import audit
from ..extensions import db
from ..models import Order, User
from ..services import inventory as stock
from ..services import order_report, report_export as rx
from ..services.xlsx_export import INT, MONEY, TEXT
from . import bp
from .inventory import inventory_query
from .orders import CONFIRMED_STATUSES, NOT_CONFIRMED_STATUSES, order_filters

STOCK_LABELS = {"out": "Out of stock", "low": "Low stock", "ok": "In stock"}


def _stamp() -> str:
    return datetime.now(shop_tz()).strftime("%Y-%m-%d")


def _deliver(report: rx.Report, fmt: str):
    return rx.xlsx_response(report, _stamp()) if fmt == "xlsx" else rx.csv_response(report, _stamp())


# ------------------------------------------------------------------ orders
@bp.get("/orders/export.<fmt>")
def orders_export(fmt):
    if fmt not in ("csv", "xlsx"):
        return Response(status=404)
    where, show, unpaid, term = order_filters()
    q = select(Order).join(User, User.id == Order.user_id).where(*where)
    if show == "confirmed":
        q = q.where(Order.status.in_(CONFIRMED_STATUSES))
    elif show == "not_confirmed":
        q = q.where(Order.status.in_(NOT_CONFIRMED_STATUSES))
    total = db.session.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    rows = db.session.scalars(q.options(joinedload(Order.user), selectinload(Order.items))
                              .order_by(Order.created_at.desc(), Order.id.desc()).limit(rx.MAX_EXPORT_ROWS)).all()
    bits = [{"all": "all orders", "confirmed": "confirmed orders", "not_confirmed": "not yet confirmed"}[show]]
    if unpaid:
        bits.append("payment pending")
    if term:
        bits.append(f"search “{term}”")
    report = order_report.build_orders_report(rows, tz=shop_tz(), include_email=False, filters_text=", ".join(bits),
                                              truncated_from=total if total > len(rows) else None, who=g.user.name)
    audit("order.export", "order", None, actor_id=g.user.id, after={"count": len(rows), "format": fmt, "filters": dict(request.args)})
    db.session.commit()
    return _deliver(report, fmt)


# ------------------------------------------------------------------ stock
@bp.get("/inventory/export.<fmt>")
def inventory_export(fmt):
    if fmt not in ("csv", "xlsx"):
        return Response(status=404)
    q, sort = inventory_query()
    products = db.session.scalars(q.limit(rx.MAX_EXPORT_ROWS)).unique().all()
    headers = ["SKU", "Product", "Category", "Brand", "Pack Size", "Variants (stock)", "Stock Qty", "Low-Stock Alert At", "Stock Status",
               "Selling Price (₹)", "MRP (₹)", "Stock Value at Selling Price (₹)", "Listed in Shop"]
    kinds = [TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INT, INT, TEXT, MONEY, MONEY, MONEY, TEXT]
    rows, units, value, counts = [], 0, 0, {"out": 0, "low": 0, "ok": 0}
    for p in products:
        state = stock.stock_state(p.stock_qty, p.low_stock_threshold)
        counts[state] += 1
        worth = (p.final_price or 0) * max(p.stock_qty, 0)
        units += max(p.stock_qty, 0)
        value += worth
        variants = "; ".join(f"{v.option_value}: {getattr(v, 'stock_qty', 0)}" for v in p.variants)
        rows.append([p.sku, p.name, p.category.name if p.category else None, p.brand, p.pack_size, variants, p.stock_qty, p.low_stock_threshold,
                     STOCK_LABELS[state], p.final_price, p.mrp, worth, "Yes" if p.is_active else "No"])
    now = datetime.now(shop_tz())
    term, stock_filter = (request.args.get("q") or "").strip(), request.args.get("stock", "")
    notes = [f"Filters: {STOCK_LABELS.get(stock_filter, 'all stock levels')}" + (f", search “{term}”" if term else ""),
             f"Generated: {rx.dt_text(now.replace(tzinfo=None))} ({shop_tz().key}) by {g.user.name}"]
    summary = [("Products in this report", len(rows), INT), ("Units in stock", units, INT), ("In stock", counts["ok"], INT),
               ("Low stock", counts["low"], INT), ("Out of stock", counts["out"], INT), ("Stock value at selling price (₹)", value, MONEY)]
    totals = ["Total", None, None, None, None, None, units, None, None, None, None, value, None]
    report = rx.Report(title="RR FOODS — Stock report", filename="rr-foods-stock", sheet_name="Stock", headers=headers, kinds=kinds, rows=rows,
                       notes=notes, summary=summary, totals=totals)
    audit("inventory.export", "product", None, actor_id=g.user.id, after={"count": len(rows), "format": fmt, "filters": dict(request.args)})
    db.session.commit()
    return _deliver(report, fmt)
