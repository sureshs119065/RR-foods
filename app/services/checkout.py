"""Checkout. It validates everything and records an order REQUEST (status "pending_whatsapp"), nothing more.

An order only becomes real when the customer's WhatsApp message reaches the shop and the shop confirms it
(services.orders.confirm_whatsapp_received). Until then no stock is taken, no coupon is used, the cart is untouched and the
owner's queues and sales do not see it. So opening WhatsApp, or even closing the website, can never place an order by itself.
"""
import secrets
from datetime import datetime
from decimal import Decimal

from flask import current_app
from sqlalchemy import select

from ..auth.service import audit
from ..extensions import db
from ..models import Address, CartItem, CouponUsage, DeliveryZone, Order, OrderItem, OrderStatusHistory, Payment, Product, ProductVariant
from ..models.base import utcnow
from ..models.orders import DRAFT_STATUS
from . import coupons, inventory
from .cart import MAX_LINE_QTY, q2, totals_for, Line


class CheckoutError(Exception):
    """Safe to show to the customer. Nothing was saved."""


WHATSAPP_METHOD = "upi_manual"  # stored on the order; payment is settled with the owner on WhatsApp, then marked paid in the owner panel


def payment_methods() -> list[tuple[str, str, str]]:
    return [(WHATSAPP_METHOD, "Order and pay on WhatsApp", "No payment now. Send your order to the shop on WhatsApp. It is placed only once the shop receives your message and confirms it.")]


def zone_for(pincode: str) -> DeliveryZone | None:
    from .delivery import zone_for as delivery_zone_for
    return delivery_zone_for(pincode)


def snapshot(a: Address) -> dict:
    return {"label": a.label, "full_name": a.full_name, "phone": a.phone, "line1": a.line1, "line2": a.line2, "city": a.city, "state": a.state, "pincode": a.pincode}


def new_order_number() -> str:
    for _ in range(10):
        n = f"NK{utcnow():%y%m%d}{secrets.randbelow(100000):05d}"
        if not db.session.scalar(select(Order.id).where(Order.order_number == n)):
            return n
    raise CheckoutError("We could not create an order number. Please try again.")


def _check_bundle_still_valid(item: CartItem, product: Product) -> None:
    """A bundle price is saved in the cart when the customer adds the bundle. Before it is charged, make sure the bundle is still
    live and was not edited since (a changed price, product list or schedule means the saved price may be wrong)."""
    from ..models.content import Bundle
    bundle = db.session.get(Bundle, item.bundle_id) if item.bundle_id else None
    now = utcnow()
    if bundle is None or not bundle.is_active or (bundle.starts_at and bundle.starts_at > now) or (bundle.ends_at and bundle.ends_at <= now):
        raise CheckoutError(f"The bundle offer for “{product.name}” has ended. Remove it from your cart and try again.")
    if bundle.updated_at and item.created_at and bundle.updated_at > item.created_at:
        raise CheckoutError(f"The bundle offer for “{product.name}” was updated. Remove it from your cart and add the bundle again to get the new price.")


def _signature(items) -> tuple:
    return tuple(sorted((i["product_id"], i["variant_id"] or 0, i["quantity"]) for i in items))


def create_pending_order(user, address_id: int, method: str, coupon_code: str | None, note: str | None, gift_message: str | None = None, hide_prices: bool = False) -> Order:
    """Validate the cart and save it as an order request waiting for the WhatsApp message. Takes nothing from stock or coupons."""
    if method not in {m[0] for m in payment_methods()}:
        raise CheckoutError("Choose a payment method.")
    address = db.session.get(Address, address_id) if address_id else None
    if address is None or address.user_id != user.id:
        raise CheckoutError("Choose a delivery address.")
    zone = zone_for(address.pincode)
    if zone is None or not zone.is_serviceable:
        raise CheckoutError(f"Sorry, we do not deliver to {address.pincode} yet. Choose another address.")

    items = list(db.session.scalars(select(CartItem).where(CartItem.user_id == user.id, CartItem.saved_for_later.is_(False)).order_by(CartItem.id)))
    if not items:
        raise CheckoutError("Your cart is empty. Your order may already have been placed. Check My orders.")

    pids = sorted({i.product_id for i in items})
    vids = sorted({i.variant_id for i in items if i.variant_id})
    products = {p.id: p for p in db.session.scalars(select(Product).where(Product.id.in_(pids)).order_by(Product.id))}
    variants = {v.id: v for v in db.session.scalars(select(ProductVariant).where(ProductVariant.id.in_(vids)).order_by(ProductVariant.id))} if vids else {}

    lines: list[Line] = []
    for it in items:
        p, v = products.get(it.product_id), variants.get(it.variant_id) if it.variant_id else None
        if p is None or p.is_deleted or not p.is_active:
            raise CheckoutError("An item in your cart is no longer available. Remove it and try again.")
        if v is None and any(x.is_active and not x.is_deleted for x in p.variants):
            raise CheckoutError(f"Choose an option for “{p.name}” on its product page.")
        if v is not None and (v.is_deleted or not v.is_active or v.product_id != p.id):
            raise CheckoutError(f"That option of “{p.name}” is no longer available. Remove it and try again.")
        if it.bundle_id or it.unit_price_override is not None:
            _check_bundle_still_valid(it, p)
        stock = v.stock_qty if v else p.stock_qty
        name = p.name + (f" ({v.option_value})" if v else "")
        if it.quantity > MAX_LINE_QTY:
            raise CheckoutError(f"You can buy at most {MAX_LINE_QTY} of “{name}” in one order.")
        if stock < it.quantity:  # checked again, with locks, when the shop confirms the WhatsApp message
            raise CheckoutError(f"“{name}” is {'out of stock' if stock <= 0 else f'down to {stock}'}. Update your cart and try again.")
        price, mrp = (v.price, v.mrp or v.price) if v else (it.unit_price_override if it.unit_price_override is not None else p.final_price, p.mrp)
        lines.append(Line(item=it, product=p, variant=v, unit_price=Decimal(price), mrp=Decimal(mrp), stock=stock, error=None, qty=it.quantity))

    subtotal = q2(sum((l.total for l in lines), Decimal(0)))
    coupon, discount = None, Decimal(0)
    if coupon_code:
        coupon = coupons.find(coupon_code)
        try:
            if coupon is None:
                raise coupons.CouponError("That coupon code does not exist.")
            discount = coupons.discount_for(coupon, user.id, subtotal)
        except coupons.CouponError as e:
            raise CheckoutError(f"Coupon problem: {e}") from e
    t = totals_for(lines, discount, zone)

    # The same request sent twice (back button, second tap) is one request, not two. A changed cart replaces the old request.
    open_requests = list(db.session.scalars(select(Order).where(Order.user_id == user.id, Order.status == DRAFT_STATUS).order_by(Order.id.desc()).with_for_update()))
    wanted = _signature([{"product_id": l.product.id, "variant_id": l.variant.id if l.variant else None, "quantity": l.qty} for l in lines])
    for old in open_requests:
        same = _signature([{"product_id": i.product_id, "variant_id": i.variant_id, "quantity": i.quantity} for i in old.items]) == wanted \
            and old.total == t.total and old.shipping_address == snapshot(address) and (old.coupon_code or None) == (coupon.code if coupon else None)
        if same:
            return old
    for old in open_requests:
        old.status = "cancelled"
        old.updated_at = utcnow()
        db.session.add(OrderStatusHistory(order_id=old.id, from_status=DRAFT_STATUS, to_status="cancelled", changed_by=user.id, note="Replaced by a newer checkout"))

    order = Order(order_number=new_order_number(), user_id=user.id, status=DRAFT_STATUS, shipping_address=snapshot(address),
                  subtotal=t.subtotal, discount_total=t.discount, delivery_fee=t.delivery or Decimal(0), tax_total=t.tax_included, total=t.total,
                  coupon_id=coupon.id if coupon else None, coupon_code=coupon.code if coupon else None, payment_method=method,
                  payment_status="pending", customer_notes=(note or "").strip()[:500] or None,
                  gift_message=(gift_message or "").strip()[:500] or None, hide_prices=bool(hide_prices))
    for l in lines:
        order.items.append(OrderItem(product_id=l.product.id, variant_id=l.variant.id if l.variant else None,
                                     name=l.product.name + (f" ({l.variant.option_value})" if l.variant else ""), sku=l.sku, pack_size=l.product.pack_size,
                                     unit_price=l.unit_price, mrp=l.mrp, quantity=l.qty, line_total=l.total))
    order.payments.append(Payment(provider="upi_manual", amount=t.total, status="pending"))
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderStatusHistory(order_id=order.id, from_status=None, to_status=DRAFT_STATUS, changed_by=user.id, note="Waiting for the WhatsApp message"))
    audit("order.request", entity_type="order", entity_id=order.id, actor_id=user.id, after={"order_number": order.order_number, "total": str(order.total), "method": method})
    return order


place_order = create_pending_order  # old name, kept so existing callers keep working: it only records a request
