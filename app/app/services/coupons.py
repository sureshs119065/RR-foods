"""Coupon rules, in one place so the cart, checkout and order rejection/cancellation all agree."""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select

from ..extensions import db
from ..models import Coupon, CouponUsage
from ..models.base import utcnow


class CouponError(Exception):
    """Safe to show to the customer."""


def normalize_code(raw: str | None) -> str:
    return "".join((raw or "").upper().split())[:40]


def find(code: str, lock: bool = False) -> Coupon | None:
    q = select(Coupon).where(func.upper(Coupon.code) == normalize_code(code))
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return db.session.scalar(q)


def discount_for(coupon: Coupon, user_id: int, subtotal: Decimal) -> Decimal:
    """The rupee discount, or CouponError saying why the code cannot be used."""
    now = utcnow()
    if not coupon.is_active:
        raise CouponError("This coupon is not active.")
    if coupon.expires_at and coupon.expires_at <= now:
        raise CouponError("This coupon has expired.")
    if subtotal < coupon.min_cart_value:
        raise CouponError(f"Add items worth ₹{coupon.min_cart_value - subtotal:,.2f} more to use {coupon.code}. Minimum cart value is ₹{coupon.min_cart_value:,.2f}.")
    if coupon.usage_limit is not None and coupon.used_count >= coupon.usage_limit:
        raise CouponError("This coupon has been fully used.")
    if coupon.per_user_limit and coupon.per_user_limit > 0:
        mine = db.session.scalar(select(func.count(CouponUsage.id)).where(CouponUsage.coupon_id == coupon.id, CouponUsage.user_id == user_id)) or 0
        if mine >= coupon.per_user_limit:
            raise CouponError("You have already used this coupon the maximum number of times.")
    if coupon.discount_type == "percent":
        amount = subtotal * coupon.discount_value / Decimal(100)
        if coupon.max_discount is not None:
            amount = min(amount, coupon.max_discount)
    else:
        amount = coupon.discount_value
    return min(amount, subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def release(order) -> None:
    """Give back the coupon use of a rejected or cancelled order. Evidence-based: only if a usage row exists."""
    if not order.coupon_id:
        return
    used = db.session.scalars(select(CouponUsage).where(CouponUsage.order_id == order.id)).all()
    if not used:
        return
    coupon = db.session.get(Coupon, order.coupon_id, with_for_update=True)
    if coupon:
        coupon.used_count = max(0, coupon.used_count - len(used))
    for u in used:
        db.session.delete(u)
