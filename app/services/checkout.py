"""Placing an order. One transaction: lock the stock rows, re-check everything, take the stock, record the order.

Why the locks matter: two customers buying the last item at the same moment must not both succeed. Product and variant rows are
locked in a fixed order (products by id, then variants by id) so two checkouts can never deadlock each other.
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
from . import coupons, inventory
from .cart import MAX_LINE_QTY, q2, totals_for, Line
from .notify import notify
from . import delivery_slots


class CheckoutError(Exception):
    """Safe to show to the customer. Nothing was saved."""


WHATSAPP_METHOD = "upi_manual"  # stored on the order; payment is settled with the owner on WhatsApp, then marked paid in the owner panel


def payment_methods() -> list[tuple[str, str, str]]:
    return [(WHATSAPP_METHOD, "Order and pay on WhatsApp", "No payment now. Send your order on WhatsApp and the shop will confirm it and share payment details.")]


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


def place_order(user, address_id: int, method: str, coupon_code: str | None, note: str | None, delivery_date: str | None = None, delivery_slot: str | None = None) -> Order:
    if method not in {m[0] for m in payment_methods()}:
        raise CheckoutError("Choose a payment method.")
    address = db.session.get(Address, address_id) if address_id else None
    if address is None or address.user_id != user.id:
        raise CheckoutError("Choose a delivery address.")
    zone = zone_for(address.pincode)
    if zone is None or not zone.is_serviceable:
        raise CheckoutError(f"Sorry, we do not deliver to {address.pincode} yet. Choose another address.")

    if not delivery_date and not delivery_slot:  # legacy clients without slot fields get the first server-validated available slot
        delivery_date, delivery_slot = delivery_slots.first_available()
    try:
        chosen_delivery_date, chosen_delivery_slot = delivery_slots.validate_and_lock(delivery_date, delivery_slot)
    except ValueError as exc:
        raise CheckoutError(str(exc)) from exc

    items = list(db.session.scalars(select(CartItem).where(CartItem.user_id == user.id, CartItem.saved_for_later.is_(False)).order_by(CartItem.id)))
    if not items:
        raise CheckoutError("Your cart is empty. Your order may already have been placed. Check My orders.")

    # lock every stock row we are about to read, in a fixed order
    pids = sorted({i.product_id for i in items})
    vids = sorted({i.variant_id for i in items if i.variant_id})
    products = {p.id: p for p in db.session.scalars(select(Product).where(Product.id.in_(pids)).order_by(Product.id).with_for_update().execution_options(populate_existing=True))}
    variants = {v.id: v for v in db.session.scalars(select(ProductVariant).where(ProductVariant.id.in_(vids)).order_by(ProductVariant.id).with_for_update().execution_options(populate_existing=True))} if vids else {}

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
        if stock < it.quantity:  # the stock re-check at placement
            raise CheckoutError(f"“{name}” is {'out of stock' if stock <= 0 else f'down to {stock}'}. Update your cart and try again.")
        price, mrp = (v.price, v.mrp or v.price) if v else (it.unit_price_override if it.unit_price_override is not None else p.final_price, p.mrp)
        lines.append(Line(item=it, product=p, variant=v, unit_price=Decimal(price), mrp=Decimal(mrp), stock=stock, error=None, qty=it.quantity))

    subtotal = q2(sum((l.total for l in lines), Decimal(0)))
    coupon, discount = None, Decimal(0)
    if coupon_code:
        coupon = coupons.find(coupon_code, lock=True)
        try:
            if coupon is None:
                raise coupons.CouponError("That coupon code does not exist.")
            discount = coupons.discount_for(coupon, user.id, subtotal)
        except coupons.CouponError as e:
            raise CheckoutError(f"Coupon problem: {e}") from e
    t = totals_for(lines, discount, zone)

    order = Order(order_number=new_order_number(), user_id=user.id, status="placed", shipping_address=snapshot(address),
                  subtotal=t.subtotal, discount_total=t.discount, delivery_fee=t.delivery or Decimal(0), tax_total=t.tax_included, total=t.total,
                  coupon_id=coupon.id if coupon else None, coupon_code=coupon.code if coupon else None, payment_method=method,
                  payment_status="pending", customer_notes=(note or "").strip()[:500] or None,
                  delivery_date=chosen_delivery_date, delivery_slot=chosen_delivery_slot)
    for l in lines:
        order.items.append(OrderItem(product_id=l.product.id, variant_id=l.variant.id if l.variant else None,
                                     name=l.product.name + (f" ({l.variant.option_value})" if l.variant else ""), sku=l.sku, pack_size=l.product.pack_size,
                                     unit_price=l.unit_price, mrp=l.mrp, quantity=l.qty, line_total=l.total))
    order.payments.append(Payment(provider="upi_manual", amount=t.total, status="pending"))
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderStatusHistory(order_id=order.id, from_status=None, to_status="placed", changed_by=user.id, note=None))

    for l in lines:  # take the stock; the reason names the order so the owner's stock history explains itself
        inventory.add_quantity(l.variant or l.product, -l.qty, f"order {order.order_number} placed", None)
    if coupon:
        coupon.used_count += 1
        db.session.add(CouponUsage(coupon_id=coupon.id, user_id=user.id, order_id=order.id))
    for it in items:
        db.session.delete(it)

    notify(user.id, "order_status", f"Order {order.order_number} placed", "Thanks! Send the order on WhatsApp so the shop can confirm it and share payment details.", link=f"/account/orders/{order.order_number}")
    audit("order.place", entity_type="order", entity_id=order.id, actor_id=user.id, after={"order_number": order.order_number, "total": str(order.total), "method": method})
    return order
