"""WhatsApp-first ordering helpers. No API, no cost, no approval: everything is a wa.me link with a ready-written message.

  customer -> owner : after checkout the customer taps "Send order on WhatsApp" (order_message / owner_link)
  owner -> customer : the owner order pages have a "Message customer on WhatsApp" button (status_message / customer_link)

Payment is settled between the owner and the customer on WhatsApp; the owner then marks the order Paid in the owner panel.
"""
import re
from decimal import Decimal
from urllib.parse import quote

from flask import current_app, url_for


def clean_number(raw: str | None) -> str:
    """Digits only, with the country code, as wa.me needs. A 10 digit Indian mobile gets DEFAULT_COUNTRY_CODE in front."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = current_app.config.get("DEFAULT_COUNTRY_CODE", "91") + digits
    return digits


def owner_number() -> str:
    cfg = current_app.config
    return clean_number(cfg.get("ADMIN_WHATSAPP_NUMBER") or cfg.get("WHATSAPP_NUMBER"))


def link(number: str, text: str = "") -> str | None:
    if not number:
        return None
    return f"https://wa.me/{number}" + (f"?text={quote(text, safe='')}" if text else "")


def _inr(v) -> str:
    return f"₹{Decimal(v or 0):,.2f}"


def _customer(order) -> tuple[str, str, str]:
    a = order.shipping_address or {}
    name = a.get("full_name") or (order.user.name if order.user else "Customer")
    phone = a.get("phone") or (order.user.phone if order.user else "") or ""
    parts = [a.get("line1"), a.get("line2"), a.get("city"), a.get("state"), a.get("pincode")]
    return name, phone, ", ".join(str(p) for p in parts if p)


def order_message(order) -> str:
    """The message the customer sends to the owner."""
    shop = current_app.config.get("SHOP_NAME", "RR FOODS")
    name, phone, address = _customer(order)
    lines = [f"Hello {shop}, I would like to place this order.", "", f"Order: {order.order_number}", "Items:"]
    for i, it in enumerate(order.items, 1):
        pack = f" [{it.pack_size}]" if it.pack_size else ""
        lines.append(f"{i}. {it.name}{pack} x {it.quantity} = {_inr(it.line_total)}")
    lines.append("")
    if order.discount_total:
        lines.append(f"Discount{' (' + order.coupon_code + ')' if order.coupon_code else ''}: -{_inr(order.discount_total)}")
    lines.append(f"Delivery: {_inr(order.delivery_fee)}")
    if getattr(order, "delivery_date", None):
        lines.append(f"Preferred delivery: {order.delivery_date:%d %b %Y} · {order.delivery_slot or 'To be confirmed'}")
    lines.append(f"Total: {_inr(order.total)}")
    lines += ["", f"Name: {name}", f"Phone: {phone}", f"Address: {address}"]
    if order.customer_notes:
        lines.append(f"Note: {order.customer_notes}")
    lines += ["", "Please confirm my order and share the payment details. Thank you!"]
    return "\n".join(lines)


def owner_link(order) -> str | None:
    """customer -> owner: opens WhatsApp with the order already written."""
    return link(owner_number(), order_message(order))


def status_message(order) -> str:
    """The message the owner sends to the customer, matched to where the order is now."""
    shop = current_app.config.get("SHOP_NAME", "RR FOODS")
    name, _, _ = _customer(order)
    n, total, paid = order.order_number, _inr(order.total), order.payment_status == "paid"
    try:
        track = url_for("shop.order_detail", order_number=n, _external=True)
    except RuntimeError:  # no request context
        track = ""
    pay_line = "Payment received, thank you." if paid else f"Please pay {total} and send us the payment screenshot here."
    s = order.status
    if s == "placed":
        body = f"we received your order {n} (total {total}). {pay_line} We will confirm it right after."
    elif s == "confirmed":
        body = f"your order {n} is confirmed. {pay_line}"
    elif s == "packed":
        body = f"your order {n} is packed and will be shipped soon. {'' if paid else pay_line}".strip()
    elif s == "shipped":
        body = f"your order {n} is on its way. {'Track it here: ' + track if track else ''}".strip()
    elif s == "out_for_delivery":
        body = f"your order {n} is out for delivery and will reach you soon. {'Track it here: ' + track if track else ''}".strip()
    elif s == "delivered":
        body = f"your order {n} was delivered. Thank you for shopping with us!"
    elif s == "rejected":
        body = f"sorry, we could not accept order {n}. Reason: {order.rejection_reason or 'not available'}."
    elif s == "cancelled":
        body = f"your order {n} was cancelled."
    else:
        body = f"here is an update on your order {n}: {s.replace('_', ' ')}."
    return f"Hi {name}, {body}\n- {shop}"


def customer_link(order) -> str | None:
    """owner -> customer: opens WhatsApp with a status message already written."""
    _, phone, _ = _customer(order)
    return link(clean_number(phone), status_message(order))
