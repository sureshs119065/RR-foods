"""Order status changes made by the owner.

Allowed moves (forward only, no skipping):
    placed -> confirmed -> packed -> shipped -> out_for_delivery -> delivered
    (out_for_delivery is optional: shipped -> delivered is still allowed)
    placed / confirmed / packed -> rejected   (optional reason; before it ships)
Customer cancellation, returns and refunds are Step 6/7.

What a move does, all in ONE database transaction (the caller commits):
  1. locks the order row, so two people cannot move the same order at once;
  2. refuses if the page the owner was looking at is out of date (expected_from);
  3. writes order_status_history (who, when, note);
  4. rejected: puts the stock back (with inventory log rows) and frees any coupon use;
     delivered: marks a cash-on-delivery order as paid;
  5. sends the customer an in-app notification;
  6. writes an audit log entry.

Contract with checkout (Step 6): stock is taken off the shelf when the order is placed, and a coupon use row is written then.
Rejecting gives both back.
"""
from sqlalchemy import select, update

from ..auth.service import audit
from ..extensions import db
from ..models import Order, OrderItem, OrderStatusHistory, Product, User
from ..models.base import utcnow
from .coupons import release as release_coupon
from .inventory import restore_order_stock
from .notify import notify

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "placed": ("confirmed", "rejected"),
    "confirmed": ("packed", "rejected"),
    "packed": ("shipped", "rejected"),
    "shipped": ("out_for_delivery", "delivered"),
    "out_for_delivery": ("delivered",),
    # returns: the customer asks (request_return); the owner accepts (-> returned), turns it down (-> delivered, reason needed) and later marks it refunded
    "return_requested": ("returned", "delivered"),
    "returned": ("refunded",),
}
# Moves that count as revenue: the shop has accepted the order and it has not been turned away or cancelled.
REVENUE_STATUSES = ("confirmed", "packed", "shipped", "out_for_delivery", "delivered")

LABELS = {
    "placed": "Placed", "confirmed": "Confirmed", "rejected": "Rejected", "packed": "Packed", "shipped": "Shipped",
    "out_for_delivery": "Out for delivery", "delivered": "Delivered", "cancelled": "Cancelled", "return_requested": "Return requested", "returned": "Returned",
    "refunded": "Refunded",
}
ACTION_LABELS = {"confirmed": "Mark confirmed", "packed": "Mark packed", "shipped": "Mark shipped", "out_for_delivery": "Mark out for delivery", "delivered": "Mark delivered",
                 "returned": "Accept return", "refunded": "Mark refunded"}
REASON_MIN, REASON_MAX = 5, 300


class OrderError(Exception):
    """Safe to show to the owner."""


class StaleOrder(OrderError):
    pass


def next_step(status: str) -> str | None:
    """The one forward step for the big button (never 'rejected')."""
    return next((t for t in TRANSITIONS.get(status, ()) if t != "rejected"), None)


def can_reject(status: str) -> bool:
    return "rejected" in TRANSITIONS.get(status, ())


def lock_order(order_id: int) -> Order | None:
    return db.session.scalar(select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True))


def _set_paid(order: Order, paid: bool) -> None:
    target = "paid" if paid else "pending"
    order.payment_status = target
    for p in order.payments:
        if p.status in ("pending", "paid"):
            p.status = target


def change_status(order_id: int, to: str, actor, reason: str | None = None, expected_from: str | None = None, restock: bool = False,
                  mark_paid: bool = False) -> Order:
    order = lock_order(order_id)
    if order is None:
        raise OrderError("That order no longer exists.")
    current = order.status
    if expected_from and expected_from != current:
        raise StaleOrder(f"This order is now “{LABELS.get(current, current)}”, so nothing was changed. Reload to see the latest.")
    if to not in TRANSITIONS.get(current, ()):
        raise OrderError(f"An order that is “{LABELS.get(current, current)}” cannot be moved to “{LABELS.get(to, to)}”.")

    reason = " ".join((reason or "").split())
    return_declined = current == "return_requested" and to == "delivered"
    if return_declined and not (REASON_MIN <= len(reason) <= REASON_MAX):
        raise OrderError(f"Give the customer a reason ({REASON_MIN} to {REASON_MAX} characters).")
    if to == "rejected" and reason and len(reason) > REASON_MAX:
        raise OrderError(f"The rejection reason must be {REASON_MAX} characters or fewer.")

    order.status = to
    order.updated_at = utcnow()
    db.session.add(OrderStatusHistory(order_id=order.id, from_status=current, to_status=to, changed_by=actor.id,
                                      note=reason or None))

    if to == "confirmed" and mark_paid and order.payment_status == "pending":
        _set_paid(order, True)  # the owner has already received the money on WhatsApp
    if to == "rejected":
        order.rejection_reason = reason or None
        restore_order_stock(order, f"order {order.order_number} rejected", actor.id)
        release_coupon(order)
    elif to == "delivered" and order.payment_method == "cod" and order.payment_status == "pending":
        order.payment_status = "paid"  # cash was collected at the door
        for p in order.payments:
            if p.status == "pending":
                p.status = "paid"
    if to == "delivered" and current in ("shipped", "out_for_delivery"):  # not when a declined return puts the order back to delivered
        for it in order.items:  # drives "popular" sorting in the shop; atomic, so no lost updates
            if it.product_id:
                db.session.execute(update(Product).where(Product.id == it.product_id).values(sales_count=Product.sales_count + it.quantity))

    elif to == "returned" and restock:
        restore_order_stock(order, f"order {order.order_number} returned and restocked", actor.id)
    elif to == "refunded":
        if order.payment_status == "paid":
            order.payment_status = "refunded"
        for p in order.payments:
            if p.status == "paid":
                p.status = "refunded"

    _notify_customer(order, "return_declined" if return_declined else to, reason)
    audit(f"order.{'return_declined' if return_declined else to}", entity_type="order", entity_id=order.id, actor_id=actor.id,
          before={"status": current}, after={"status": to, "order_number": order.order_number, "payment_status": order.payment_status, **({"reason": reason} if reason else {})})
    return order


NO_PAYMENT_CHANGE = ("rejected", "cancelled", "refunded")


def set_payment(order_id: int, paid: bool, actor) -> tuple[Order, bool]:
    """Owner marks an order paid (money received on WhatsApp) or not paid. Returns (order, changed). The caller commits."""
    order = lock_order(order_id)
    if order is None:
        raise OrderError("That order no longer exists.")
    if order.status in NO_PAYMENT_CHANGE or order.payment_status not in ("pending", "paid"):
        raise OrderError(f"Payment cannot be changed on an order that is “{LABELS.get(order.status, order.status)}”.")
    target = "paid" if paid else "pending"
    if order.payment_status == target:
        return order, False
    before = order.payment_status
    _set_paid(order, paid)
    order.updated_at = utcnow()
    db.session.add(OrderStatusHistory(order_id=order.id, from_status=order.status, to_status=order.status, changed_by=actor.id,
                                      note="Payment marked as received" if paid else "Payment marked as not received"))
    if paid:
        notify(order.user_id, "order_status", f"Payment received for order {order.order_number}", "Thank you! The shop has received your payment.",
               link=f"/account/orders/{order.order_number}")
    audit("order.payment_paid" if paid else "order.payment_unpaid", entity_type="order", entity_id=order.id, actor_id=actor.id,
          before={"payment_status": before}, after={"payment_status": target, "order_number": order.order_number})
    return order, True


_MESSAGES = {
    "confirmed": ("Order {n} confirmed", "Great news! Your order has been confirmed and is being prepared."),
    "packed": ("Order {n} is packed", "Your order is packed and waiting for pickup by the courier."),
    "shipped": ("Order {n} shipped", "Your order is on its way! Get ready to receive your package."),
    "out_for_delivery": ("Order {n} is out for delivery", "Exciting! Your order is out for delivery and will reach you soon."),
    "delivered": ("Order {n} delivered", "Your order has been successfully delivered. We hope you love your purchase! Tap to rate your products."),
    "rejected": ("Order {n} could not be accepted", "Sorry, the shop could not fulfil this order.{reason_text}"),
    "returned": ("Return accepted for order {n}", "We have accepted your return. Your refund will follow."),
    "refunded": ("Refund issued for order {n}", "Your refund has been issued. It can take a few days to show in your account."),
    "return_declined": ("Return not accepted for order {n}", "Sorry, we could not accept this return. Reason: {r}"),
}


def _notify_customer(order: Order, to: str, reason: str) -> None:
    title, body = _MESSAGES[to]
    if to == "confirmed" and order.payment_status == "paid":
        body += " We have also received your payment."
    if to == "rejected":
        body = body.format(reason_text=f" Reason: {reason}" if reason else "")
        if order.payment_status == "paid":
            body += " Your payment will be refunded."
    else:
        body = body.format(r=reason)
    notify(order.user_id, "return_status" if to in ("returned", "refunded", "return_declined") else "order_status", title.format(n=order.order_number), body,
           link=f"/account/orders/{order.order_number}")


CANCELLABLE = ("placed", "confirmed", "packed")  # a customer may cancel until the parcel is shipped


def cancel_by_customer(order_id: int, user) -> Order:
    """Customer cancels their own order before it ships. Same safety rules as a rejection (lock, history, stock back, coupon back)."""
    order = lock_order(order_id)
    if order is None or order.user_id != user.id:
        raise OrderError("We could not find that order.")
    if order.status not in CANCELLABLE:
        raise OrderError("This order has already shipped or is closed, so it can no longer be cancelled.")
    current = order.status
    order.status = "cancelled"
    order.updated_at = utcnow()
    db.session.add(OrderStatusHistory(order_id=order.id, from_status=current, to_status="cancelled", changed_by=user.id, note="Cancelled by customer"))
    restore_order_stock(order, f"order {order.order_number} cancelled by customer", None)
    release_coupon(order)
    audit("order.cancelled_by_customer", entity_type="order", entity_id=order.id, actor_id=user.id,
          before={"status": current}, after={"status": "cancelled", "order_number": order.order_number})
    for owner_id in db.session.scalars(select(User.id).where(User.role == "owner", User.is_deleted.is_(False), User.is_blocked.is_(False))):
        notify(owner_id, "order_cancelled", f"Order {order.order_number} was cancelled by the customer",
               "The items are back in stock." + (" It was paid online: refund the customer." if order.payment_status == "paid" else ""),
               link=f"/owner/orders/{order.id}")
    return order


RETURN_REASONS = ("Damaged or leaking", "Wrong item received", "Quality not as expected", "Item expired or near expiry", "Ordered by mistake", "Other")


def return_deadline(order: Order):
    """The last moment a return can be requested: delivery time plus the return window (site setting return_window_days, default 7)."""
    from datetime import timedelta
    from .storefront import setting
    delivered = db.session.scalar(select(OrderStatusHistory.created_at).where(OrderStatusHistory.order_id == order.id, OrderStatusHistory.to_status == "delivered")
                                  .order_by(OrderStatusHistory.id.desc()).limit(1)) or order.updated_at
    try:
        days = int(setting("return_window_days", 7))
    except (TypeError, ValueError):
        days = 7
    return delivered + timedelta(days=max(0, days))


def request_return(order_id: int, user, reason: str, note: str | None) -> Order:
    """Customer asks to return a delivered order, inside the return window. The owner decides."""
    order = lock_order(order_id)
    if order is None or order.user_id != user.id:
        raise OrderError("We could not find that order.")
    if order.status != "delivered":
        raise OrderError("Only delivered orders can be returned." if order.status != "return_requested" else "A return is already requested for this order.")
    if utcnow() > return_deadline(order):
        raise OrderError("The return period for this order is over.")
    if reason not in RETURN_REASONS:
        raise OrderError("Choose a reason for the return.")
    note = " ".join((note or "").split())[:300]
    text = reason + (f": {note}" if note else "")
    order.status = "return_requested"
    order.updated_at = utcnow()
    db.session.add(OrderStatusHistory(order_id=order.id, from_status="delivered", to_status="return_requested", changed_by=user.id, note=text))
    audit("order.return_requested", entity_type="order", entity_id=order.id, actor_id=user.id, before={"status": "delivered"}, after={"status": "return_requested", "reason": text})
    for owner_id in db.session.scalars(select(User.id).where(User.role == "owner", User.is_deleted.is_(False), User.is_blocked.is_(False))):
        notify(owner_id, "order_return", f"Return requested for order {order.order_number}", text, link=f"/owner/orders/{order.id}")
    return order
