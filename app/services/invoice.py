"""Invoice PDF (reportlab). Built from the order's own snapshot (names, prices, address), so it never changes if the catalogue does.

Amounts are written as "Rs." because the standard PDF fonts have no rupee sign.
Seller details come from site settings: business_name, business_address, gstin. Ask your accountant what a GST invoice must contain
for your business; this layout is a clear commercial invoice, not tax advice.
"""
import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from ..admin.helpers import local_display
from .storefront import money_setting, setting

NOT_INVOICEABLE = ("placed", "rejected", "cancelled")


def rs(v) -> str:
    return f"Rs. {Decimal(v or 0):,.2f}"


def build_invoice(order) -> bytes:
    styles = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=styles["Normal"], fontName="Helvetica", fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=base, fontSize=8.5, textColor=colors.HexColor("#555555"))
    h1 = ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=colors.HexColor("#1b5e3b"))
    bold = ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold")
    right = ParagraphStyle("r", parent=base, alignment=2)
    p = lambda text, st=base: Paragraph(escape(str(text or "")).replace("\n", "<br/>"), st)

    seller = setting("business_name", "RR FOODS")
    addr_lines = str(setting("business_address", "") or "")
    gstin = str(setting("gstin", "") or "")
    a = order.shipping_address or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                            title=f"Invoice {order.order_number}", author=seller)
    out = [Paragraph("INVOICE", h1), Spacer(1, 4)]

    head = Table([[
        [p(seller, bold), p(addr_lines, small), p(f"GSTIN: {gstin}" if gstin else "", small)],
        [p(f"Invoice no: {order.order_number}", bold), p(f"Date: {local_display(order.created_at)}"), p(f"Payment: {'Cash on delivery' if order.payment_method == 'cod' else 'Online'} ({order.payment_status})")],
    ]], colWidths=[95 * mm, 80 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    out += [head, Spacer(1, 8)]

    bill = [p("Bill to / Ship to", bold), p(a.get("full_name", "")), p(a.get("phone", "")),
            p(", ".join(x for x in (a.get("line1"), a.get("line2")) if x)), p(" ".join(x for x in (f"{a.get('city', '')},", a.get("state", ""), a.get("pincode", "")) if x))]
    out += bill + [Spacer(1, 10)]

    rows = [[p("#", bold), p("Item", bold), p("Qty", bold), p("Price", bold), p("Amount", bold)]]
    for i, it in enumerate(order.items, 1):
        rows.append([p(i), p(it.name + (f"\nSKU {it.sku}" if it.sku else "")), p(it.quantity), p(rs(it.unit_price), right), p(rs(it.line_total), right)])
    t = Table(rows, colWidths=[9 * mm, 90 * mm, 14 * mm, 30 * mm, 32 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8efe9")), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    out += [t, Spacer(1, 8)]

    tot = [["Items", rs(order.subtotal)]]
    if order.discount_total:
        tot.append([f"Discount{' (' + order.coupon_code + ')' if order.coupon_code else ''}", "- " + rs(order.discount_total)])
    tot.append(["Delivery", rs(order.delivery_fee) if order.delivery_fee else "Free"])
    if order.tax_total:
        tot.append(["Tax included in total", rs(order.tax_total)])
    tot.append(["Total", rs(order.total)])
    tt = Table([[p(k, bold if k == "Total" else base), p(v, ParagraphStyle("rb", parent=right, fontName="Helvetica-Bold") if k == "Total" else right)] for k, v in tot],
               colWidths=[45 * mm, 38 * mm], hAlign="RIGHT")
    tt.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    out += [tt, Spacer(1, 14), p("Prices include applicable taxes. Thank you for shopping with us.", small)]
    doc.build(out)
    return buf.getvalue()
