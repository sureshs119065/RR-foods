"""The orders report (Excel), shared by the Admin and Owner exports.

The caller decides WHICH orders (each role applies its own list filters and permissions); this module only lays them out.
The customer's e-mail address is included for the admin only: the owner needs a name, phone and delivery area to fulfil an order.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from . import report_export as rx, report_insights
from .orders import REVENUE_STATUSES
from .xlsx_export import DATE, DATETIME, INT, MONEY, TEXT

PAYMENT_PENDING_STATUSES = ("placed", "confirmed", "packed", "shipped", "out_for_delivery", "delivered")
CLOSED_STATUSES = ("cancelled", "rejected")


def _products_text(order) -> str:
    parts = []
    for it in order.items:
        pack = f" ({it.pack_size})" if it.pack_size else ""
        parts.append(f"{it.name}{pack} × {it.quantity}")
    return "; ".join(parts)


def build_orders_report(orders, *, tz, include_email: bool, filters_text: str, truncated_from: int | None = None, who: str = "") -> rx.Report:
    headers = ["Order No.", "Order Date", "Customer Name", "Phone"]
    kinds = [TEXT, DATETIME, TEXT, TEXT]
    if include_email:
        headers.append("Email")
        kinds.append(TEXT)
    headers += ["City", "Pincode", "Product Lines", "Units", "Products Ordered", "Subtotal (₹)", "Discount (₹)", "Delivery Fee (₹)",
                "Tax (₹)", "Order Total (₹)", "Coupon", "Payment Method", "Payment Status", "Order Status", "Delivery Date",
                "Delivery Slot", "Courier", "Tracking ID"]
    kinds += [TEXT, TEXT, INT, INT, TEXT, MONEY, MONEY, MONEY, MONEY, MONEY, TEXT, TEXT, TEXT, TEXT, DATE, TEXT, TEXT, TEXT]

    rows, sales, sales_discount, sales_units, closed, unpaid = [], Decimal(0), Decimal(0), 0, 0, 0
    first = last = None
    for o in orders:
        addr = o.shipping_address or {}
        units = sum(i.quantity for i in o.items)
        created = rx.to_local(o.created_at, tz)
        if created:
            first = created if first is None or created < first else first
            last = created if last is None or created > last else last
        row = [o.order_number, created, addr.get("full_name") or (o.user.name if o.user else None), addr.get("phone") or (o.user.phone if o.user else None)]
        if include_email:
            row.append(o.user.email if o.user else None)
        row += [addr.get("city"), addr.get("pincode"), len(o.items), units, _products_text(o), o.subtotal, o.discount_total, o.delivery_fee,
                o.tax_total, o.total, o.coupon_code, rx.label(rx.PAYMENT_METHOD_LABELS, o.payment_method), rx.label(rx.PAYMENT_STATUS_LABELS, o.payment_status),
                rx.status_label(o.status), o.delivery_date, o.delivery_slot, o.courier_name, o.tracking_id]
        rows.append(row)
        if o.status in REVENUE_STATUSES:
            sales += Decimal(str(o.total or 0))
            sales_discount += Decimal(str(o.discount_total or 0))
            sales_units += units
        if o.status in CLOSED_STATUSES:
            closed += 1
        if o.payment_status == "pending" and o.status in PAYMENT_PENDING_STATUSES:
            unpaid += 1

    sales_count = sum(1 for o in orders if o.status in REVENUE_STATUSES)
    aov = (sales / sales_count) if sales_count else Decimal(0)
    now = datetime.now(tz)
    notes = [f"Filters: {filters_text}", f"Generated: {rx.dt_text(now.replace(tzinfo=None))} ({tz.key})" + (f" by {who}" if who else "")]
    if truncated_from:
        notes.append(f"Only the newest {rx.MAX_EXPORT_ROWS:,} of {truncated_from:,} matching orders are included. Narrow the dates and export again.")
    summary = [
        ("Orders in this report", len(rows), INT),
        ("Order dates covered", f"{rx.date_text(first)} to {rx.date_text(last)}" if first else rx.EMPTY, TEXT),
        ("Orders counted as sales", sales_count, INT),
        ("Total revenue (₹)", sales, MONEY),
        ("Discounts given on sales (₹)", sales_discount, MONEY),
        ("Average order value (₹)", aov, MONEY),
        ("Units sold", sales_units, INT),
        ("Cancelled / rejected orders", closed, INT),
        ("Orders with payment pending", unpaid, INT),
    ]
    return rx.Report(title="RR FOODS — Orders report", filename="rr-foods-orders", sheet_name="Orders", headers=headers, kinds=kinds,
                     rows=rows, notes=notes, summary=summary, insights=report_insights.orders_insights(orders, tz))
