"""One look for every Admin and Owner report download (Excel only).

A `Report` holds human-readable headers, typed columns, rows, an optional summary block and an optional totals row. It renders to:

* Excel: title, filters, summary block, then the table (frozen header, filter arrows, ₹ formats, real dates, totals row).
  Money columns carry "(₹)" in the header and hold real numbers, so they still add up and sort in a spreadsheet.

Rules applied everywhere: dates look like "25 Nov 2026, 03:45 PM" (shop time zone), statuses are words ("Out for delivery"), an empty
text cell is "-", an empty number is 0, and any text that could run as a spreadsheet formula (starts with = + - @ tab or CR) is
neutralised with a leading apostrophe. Numbers are never passed through the formula guard, so negative amounts stay numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .xlsx_export import DATE, DATETIME, INT, MONEY, NUMBER, PERCENT, XLSX_MIMETYPE, InsightsSheet, Sheet, build_workbook

EMPTY = "-"
MAX_EXPORT_ROWS = 20_000          # keeps one download fast and the server's memory flat; the file says so if it was cut

STATUS_LABELS = {
    "pending_whatsapp": "Awaiting WhatsApp", "placed": "Placed", "confirmed": "Confirmed", "rejected": "Rejected", "packed": "Packed",
    "shipped": "Shipped", "out_for_delivery": "Out for delivery", "delivered": "Delivered", "cancelled": "Cancelled",
    "return_requested": "Return requested", "returned": "Returned", "refunded": "Refunded",
}
PAYMENT_METHOD_LABELS = {"cod": "Cash on delivery", "online": "Online", "upi_manual": "UPI (manual)"}
PAYMENT_STATUS_LABELS = {"pending": "Pending", "paid": "Paid", "failed": "Failed", "refunded": "Refunded"}
ROLE_LABELS = {"user": "Customer", "owner": "Owner", "admin": "Admin"}


# ------------------------------------------------------------------ formatting
def safe_cell(value) -> str:
    """Text that cannot run as a formula when opened in Excel, Sheets or LibreOffice."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def clean_text(value) -> str:
    """For report cells: formula-safe text, with "-" for nothing. The placeholder is added after the guard, so it stays a plain dash."""
    text = " ".join(str(value).split()) if value is not None else ""
    return EMPTY if text in ("", EMPTY) else safe_cell(text)


def label(mapping: dict, key, fallback_title: bool = True) -> str:
    if not key:
        return EMPTY
    return mapping.get(key) or (str(key).replace("_", " ").capitalize() if fallback_title else str(key))


def status_label(status) -> str:
    return label(STATUS_LABELS, status)


def inr(value) -> str:
    """₹1,23,456.50 would be Indian grouping; we keep the international grouping the on-screen tables already use: ₹123,456.50."""
    return f"₹{_dec(value):,.2f}"


def _dec(value) -> Decimal:
    if isinstance(value, bool) or value in (None, ""):
        return Decimal(0)
    try:
        num = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)
    return num if num.is_finite() else Decimal(0)


def to_local(dt, tz):
    """A timezone-aware datetime in the shop's time zone, as a naive value (Excel has no time zones). None stays None."""
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(tz).replace(tzinfo=None)


def dt_text(dt) -> str:
    return dt.strftime("%d %b %Y, %I:%M %p") if isinstance(dt, datetime) else EMPTY


def date_text(d) -> str:
    return d.strftime("%d %b %Y") if isinstance(d, (date, datetime)) else EMPTY


def day_range_text(d_from, d_to) -> str:
    if d_from and d_to:
        return f"{date_text(d_from)} to {date_text(d_to)}"
    if d_from:
        return f"From {date_text(d_from)}"
    if d_to:
        return f"Up to {date_text(d_to)}"
    return "All dates"


# ------------------------------------------------------------------ report
@dataclass
class Report:
    title: str                                   # "Orders report"
    filename: str                                # "rr-foods-orders" (the date and extension are added)
    sheet_name: str                              # Excel tab name
    headers: list[str]
    kinds: list[str]
    rows: list[list]
    notes: list[str] = field(default_factory=list)            # filter description, generated-on line, "showing first N" warning
    summary: list[tuple] = field(default_factory=list)        # (label, value, kind)
    totals: list | None = None                                # one cell per column; None for blank
    extra_sheets: list[Sheet] = field(default_factory=list)
    insights: InsightsSheet | None = None                     # Excel only: charts + suggestions, always the last sheet


def _xlsx_text_clean(text: str) -> str:
    return text if text in ("", EMPTY) else safe_cell(text)


def _xlsx_rows(report: Report) -> list[list]:
    out = []
    for row in report.rows:
        cells = []
        for v, k in zip(row, report.kinds):
            if k in (INT, NUMBER, MONEY, PERCENT):
                cells.append(_dec(v))
            elif k in (DATETIME, DATE):
                cells.append(v if isinstance(v, (date, datetime)) else EMPTY)
            else:
                cells.append(clean_text(v))
        out.append(cells)
    return out


def render_xlsx(report: Report) -> bytes:
    main = Sheet(report.sheet_name, report.headers, report.kinds, _xlsx_rows(report), report_title=report.title,
                 notes=[n for n in report.notes if n], summary=report.summary or None, totals=report.totals)
    return build_workbook([main, *report.extra_sheets, *([report.insights] if report.insights else [])], clean=_xlsx_text_clean)


def xlsx_response(report: Report, stamp: str):
    from flask import Response
    return Response(render_xlsx(report), mimetype=XLSX_MIMETYPE, headers=_headers(report.filename, stamp, "xlsx"))


def _headers(base: str, stamp: str, ext: str) -> dict:
    return {"Content-Disposition": f"attachment; filename={base}-{stamp}.{ext}", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
