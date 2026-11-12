"""Tax Invoice PDF in the Amazon-style layout (reportlab), built from the order's own snapshot.

Prices in the shop already include tax, so per line: net = gross / (1 + rate), tax = the rest.
Order-level discount is spread across lines in proportion to their value. Delivery is its own line.
Seller details come from site settings: business_name, business_address, business_state, gstin, pan.
"""
import io
import os
from decimal import ROUND_HALF_UP, Decimal
from xml.sax.saxutils import escape

from flask import current_app
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..admin.helpers import local_display
from .storefront import money_setting, setting

NOT_INVOICEABLE = ("placed", "rejected", "cancelled")
_FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF")
_ONES = "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen Fifteen Sixteen Seventeen Eighteen Nineteen".split()
_TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()
D = Decimal


def _fonts():
    """(regular, bold, rupee symbol). DejaVu has the rupee sign; fall back to Helvetica + 'Rs.' if it is not installed."""
    for d in _FONT_DIRS:
        r, b = os.path.join(d, "DejaVuSans.ttf"), os.path.join(d, "DejaVuSans-Bold.ttf")
        if os.path.exists(r) and os.path.exists(b):
            if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("DejaVu", r))
                pdfmetrics.registerFont(TTFont("DejaVu-Bold", b))
            return "DejaVu", "DejaVu-Bold", "\u20b9"
    return "Helvetica", "Helvetica-Bold", "Rs. "


def q2(v) -> Decimal:
    return D(v or 0).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def _words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " Hundred" + (" " + _words(n % 100) if n % 100 else "")
    for div, name in ((10**7, "Crore"), (10**5, "Lakh"), (1000, "Thousand")):
        if n >= div:
            return _words(n // div) + " " + name + (" " + _words(n % div) if n % div else "")


def amount_in_words(v) -> str:
    rupees, paise = divmod(int(q2(v) * 100), 100)
    s = f"{_words(rupees)} Rupees"
    return s + (f" and {_words(paise)} Paise" if paise else "") + " only"


def build_invoice(order) -> bytes:
    F, FB, R = _fonts()
    rs = lambda v: f"{R}{q2(v):,.2f}"
    base = ParagraphStyle("b", fontName=F, fontSize=8.5, leading=11.5)
    sm = ParagraphStyle("sm", parent=base, fontSize=7.5, leading=10)
    bold = ParagraphStyle("bd", parent=base, fontName=FB)
    rt = ParagraphStyle("rt", parent=base, alignment=2)
    rtb = ParagraphStyle("rtb", parent=rt, fontName=FB)
    ctr = ParagraphStyle("ct", parent=sm, alignment=1)
    ctrb = ParagraphStyle("ctb", parent=ctr, fontName=FB)
    smb = ParagraphStyle("smb", parent=sm, fontName=FB)
    smr = ParagraphStyle("smr", parent=sm, alignment=2)
    title = ParagraphStyle("t", parent=bold, fontSize=12, leading=15, alignment=2)
    p = lambda t, st=base: Paragraph(escape(str(t or "")).replace("\n", "<br/>"), st)

    seller = str(setting("business_name", "RR FOODS"))
    seller_addr = str(setting("business_address", "") or "")
    seller_state = str(setting("business_state", "Tamil Nadu") or "").strip()
    gstin = str(setting("gstin", "") or "")
    pan = str(setting("pan", "") or "")
    a = order.shipping_address or {}
    cust = a.get("full_name", "")
    addr = [cust, a.get("line1"), a.get("line2"), ", ".join(x for x in (a.get("city"), a.get("state")) if x), a.get("pincode"), a.get("phone") and f"Phone: {a['phone']}"]
    addr_p = [p(x, base if i else bold) for i, x in enumerate(addr) if x]
    inter = bool(a.get("state")) and bool(seller_state) and a["state"].strip().lower() != seller_state.lower()
    tax_type = "IGST" if inter else "CGST+SGST"
    rate = money_setting("tax_percent", "0")
    k = D(1) + rate / D(100)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
                            title=f"Tax Invoice {order.order_number}", author=seller)
    W = 178 * mm
    out = []

    # ---- header: logo + title
    logo_path = os.path.join(current_app.root_path, "static", "img", "rr-foods-logo.png")
    logo = Image(logo_path, 20 * mm, 20 * mm) if os.path.exists(logo_path) else p(seller, ParagraphStyle("lg", parent=bold, fontSize=16, leading=20))
    head = Table([[logo, [p("Tax Invoice/Bill of Supply/Cash Memo", title), p("(Original for Recipient)", rt)]]], colWidths=[W * 0.4, W * 0.6])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    out += [head, Spacer(1, 6 * mm)]

    # ---- sold by / billing / shipping
    sold = [p("Sold By:", bold), p(seller), p(seller_addr)]
    bill = [p("Billing Address:", rtb)] + [Paragraph(escape(str(x)), rt if i else rtb) for i, x in enumerate(x for x in addr if x)]
    ship = [p("Shipping Address:", rtb)] + [Paragraph(escape(str(x)), rt if i else rtb) for i, x in enumerate(x for x in addr if x)]
    top = Table([[sold, bill], ["", ship]], colWidths=[W * 0.5, W * 0.5])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 1), (-1, 1), 6)]))
    out += [top, Spacer(1, 4 * mm)]

    ids_l = [p(f"PAN No: {pan}") if pan else "", p(f"GST Registration No: {gstin}") if gstin else ""]
    ids_l = [x for x in ids_l if x]
    when = local_display(order.created_at)
    pay = "Cash on delivery" if order.payment_method == "cod" else "Online"
    ids_r = [p(f"Invoice Number: {order.order_number}", rt), p(f"Invoice Date: {when}", rt), p(f"Payment: {pay} ({order.payment_status})", rt)]
    if getattr(order, "delivery_date", None):
        ids_r.append(p(f"Delivery slot: {order.delivery_date:%d %b %Y} · {order.delivery_slot or ''}", rt))
    ids = Table([[[p(f"Order Number: {order.order_number}", base), p(f"Order Date: {when}", base)] + ids_l, ids_r]], colWidths=[W * 0.5, W * 0.5])
    ids.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    out += [ids, Spacer(1, 4 * mm)]

    # ---- line items
    subtotal = D(order.subtotal or 0)
    disc_total = D(order.discount_total or 0)
    lines = []  # (desc, unit_net, qty, net, disc, tax, total)
    for it in order.items:
        gross = D(it.line_total)
        d_gross = q2(disc_total * gross / subtotal) if subtotal else D(0)
        paid = gross - d_gross
        net, disc = q2(gross / k), q2(d_gross / k)
        tax = q2(paid - (net - disc))
        desc = it.name + (f" ({it.pack_size})" if it.pack_size else "") + (f"\nSKU: {it.sku}" if it.sku else "")
        lines.append((desc, q2(net / it.quantity), it.quantity, net, disc, tax, paid))
    fee = D(order.delivery_fee or 0)
    if fee:
        net = q2(fee / k)
        lines.append(("Shipping Charges", net, "", net, D(0), q2(fee - net), fee))

    rows = [[p(h, ctrb) for h in ("Sl. No", "Description", "Unit Price", "Qty", "Net Amount", "Discount", "Tax Rate", "Tax Type", "Tax Amount", "Total Amount")]]
    for i, (desc, unit, qty, net, disc, tax, tot) in enumerate(lines, 1):
        rows.append([p(i if qty != "" else "", ctr), p(desc, sm), p(rs(unit), smr), p(qty, ctr), p(rs(net), smr), p(("-" + rs(disc)) if disc else rs(0), smr),
                     p(f"{rate.normalize():f}%", ctr), p(tax_type, ctr), p(rs(tax), smr), p(rs(tot), smr)])
    g_tax = sum((x[5] for x in lines), D(0))
    g_tot = sum((x[6] for x in lines), D(0))
    rows.append([p("Total:", smb), "", "", "", "", "", "", "", p(rs(g_tax), smr), p(rs(g_tot), ParagraphStyle("x", parent=smr, fontName=FB))])
    cw = [9, 40, 18, 8, 18, 16, 11, 21, 16, 18]
    cw = [c * W / sum(cw) for c in cw]
    t = Table(rows, colWidths=cw, repeatRows=1)
    last = len(rows) - 1
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9d9d9")),
        ("SPAN", (0, last), (7, last)), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    out.append(t)

    # ---- amount in words + signature
    foot = Table([[[p("Amount in Words:", bold), p(amount_in_words(g_tot))]],
                  [[p(f"For {seller}:", rtb), Spacer(1, 14 * mm), p("Authorized Signatory", rtb)]]], colWidths=[W])
    foot.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.black), ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                              ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    out += [foot, Spacer(1, 3 * mm), p("Whether tax is payable under reverse charge - No. Prices include applicable taxes.", sm)]
    doc.build(out)
    return buf.getvalue()
