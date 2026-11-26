"""The sales report downloads (Excel only), shared by the Admin and Owner dashboards so both see identical files."""
from __future__ import annotations

from datetime import date

from . import report_export as rx, report_insights
from .xlsx_export import INT, MIXED, MONEY, PERCENT, TEXT, Sheet, Typed, build_workbook


def _nice_day(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d %b %Y")
    except ValueError:
        return iso


def summary_rows(data) -> list[tuple]:
    """(label, value, kind) for the Summary. The date range comes first."""
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


def build_xlsx(data, tz=None) -> bytes:
    """Summary (with the date range), Top products, Coupons, Pincodes, then Insights (charts and suggestions)."""
    sheets = [
        Sheet("Summary", ["Metric", "Value"], [TEXT, MIXED], [[label, Typed(value, kind)] for label, value, kind in summary_rows(data)]),
        Sheet("Top products", ["Rank", "Product", "Sales (₹)"], [INT, TEXT, MONEY],
              [[n, rx.clean_text(item["label"]), item["value"]] for n, item in enumerate(data["top_products"], start=1)]),
        Sheet("Coupons", ["Coupon", "Orders", "Discount (₹)", "Sales (₹)"], [TEXT, INT, MONEY, MONEY],
              [[rx.clean_text(c["code"]), c["orders"], c["discount"], c["sales"]] for c in data["coupon_performance"]]),
        Sheet("Pincodes", ["Pincode", "Sales (₹)"], [TEXT, MONEY],
              [[rx.clean_text(item["label"]), item["value"]] for item in data["orders_by_pincode"]]),
    ]
    sheets.append(report_insights.sales_insights(data, tz))
    return build_workbook(sheets, clean=rx.safe_cell)
