"""Cart lines, availability and the price breakdown. Prices always come from the database, never from the browser."""
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask import g, session
from sqlalchemy import delete, func, select
from sqlalchemy.orm import joinedload, selectinload

from ..extensions import db
from ..models import CartItem, Coupon, DeliveryZone, Product, ProductVariant
from ..models.base import utcnow
from . import coupons
from .storefront import active_variants, money_setting

MAX_LINE_QTY = 10
MAX_GUEST_LINES = 50          # a guest browser may hold at most this many lines (keeps anonymous rows bounded)
GUEST_CART_DAYS = 14
GUEST_SESSION_KEY = "gid"
BUY_NOW_KEY = "buy_now"       # session: the one product a "Buy now" click chose. It is never written to the cart.
TWO = Decimal("0.01")


# ---------------------------------------------------------------- who owns the cart
@dataclass(frozen=True)
class CartOwner:
    """A signed-in customer (user_id) or an anonymous browser (session_id). Exactly one is set."""
    user_id: int | None = None
    session_id: str | None = None

    @property
    def is_guest(self) -> bool:
        return self.user_id is None

    def where(self):
        return CartItem.user_id == self.user_id if self.user_id is not None else CartItem.session_id == self.session_id

    def values(self) -> dict:
        return {"user_id": self.user_id} if self.user_id is not None else {"session_id": self.session_id}


def cart_owner(create: bool = False) -> CartOwner | None:
    """Owner of the current request's cart. Signed-in customers own by user id; everyone else by a random id
    kept in the session cookie. With create=False a visitor who has never added anything gets None (no cookie is set)."""
    user = g.get("user")
    if user is not None:
        return CartOwner(user_id=user.id) if user.role == "user" else None
    sid = session.get(GUEST_SESSION_KEY)
    if not sid and create:
        sid = secrets.token_urlsafe(24)
        session[GUEST_SESSION_KEY] = sid
        session.permanent = True
    return CartOwner(session_id=sid) if sid else None


def as_owner(owner) -> CartOwner:
    return owner if isinstance(owner, CartOwner) else CartOwner(user_id=int(owner))


def merge_guest_cart(user, guest_session_id: str | None) -> int:
    """Move a guest cart into the customer's cart after sign-in or sign-up. Same product/option/bundle lines are
    added together (capped at the per-line maximum and at stock); everything else is re-homed. Returns lines moved.
    Does not commit: the caller commits."""
    if not guest_session_id or user is None or user.role != "user":
        return 0
    guest_items = list(db.session.scalars(select(CartItem).where(CartItem.session_id == guest_session_id).order_by(CartItem.id)))
    moved = 0
    for gi in guest_items:
        mine = db.session.scalar(select(CartItem).where(
            CartItem.user_id == user.id, CartItem.product_id == gi.product_id,
            CartItem.variant_id.is_(None) if gi.variant_id is None else CartItem.variant_id == gi.variant_id,
            CartItem.bundle_id.is_(None) if gi.bundle_id is None else CartItem.bundle_id == gi.bundle_id))
        if mine is None:
            gi.user_id, gi.session_id = user.id, None
        else:
            stock = (gi.variant.stock_qty if gi.variant is not None else gi.product.stock_qty)
            cap = min(MAX_LINE_QTY, stock) if stock > 0 else MAX_LINE_QTY
            had = mine.quantity if not mine.saved_for_later else 0
            mine.quantity = max(1, min(had + gi.quantity, cap))
            mine.saved_for_later = mine.saved_for_later and gi.saved_for_later
            if mine.unit_price_override is not None:
                mine.line_total_override = mine.unit_price_override * mine.quantity
            db.session.delete(gi)
        moved += 1
    db.session.flush()
    return moved


def buy_now_items(user_id: int | None = None) -> list[CartItem]:
    """The single product chosen with "Buy now", as an in-memory cart line (never saved, never added to the session).
    Empty when nothing was chosen or the product was removed meanwhile. The saved cart is not read or changed."""
    spec = session.get(BUY_NOW_KEY)
    if not isinstance(spec, dict):
        return []
    try:
        pid, vid, qty = int(spec["product_id"]), spec.get("variant_id"), int(spec["qty"])
    except (KeyError, TypeError, ValueError):
        return []
    product = db.session.get(Product, pid)
    if product is None:
        return []
    variant = db.session.get(ProductVariant, int(vid)) if vid else None
    if vid and (variant is None or variant.product_id != product.id):
        return []
    item = CartItem(user_id=user_id, product_id=product.id, variant_id=variant.id if variant else None, quantity=max(1, min(qty, MAX_LINE_QTY)))
    item.product, item.variant = product, variant
    return [item]


def purge_guest_carts(days: int = GUEST_CART_DAYS) -> int:
    """Delete guest cart lines not touched for `days` days. Run daily from cron (`flask purge-guest-carts`)."""
    cutoff = utcnow() - timedelta(days=days)
    result = db.session.execute(delete(CartItem).where(CartItem.user_id.is_(None), CartItem.updated_at < cutoff))
    db.session.commit()
    return result.rowcount or 0


def q2(v) -> Decimal:
    return Decimal(v).quantize(TWO, rounding=ROUND_HALF_UP)


@dataclass
class Line:
    item: CartItem
    product: Product
    variant: ProductVariant | None
    unit_price: Decimal
    mrp: Decimal
    stock: int
    error: str | None
    qty: int

    @property
    def limit(self) -> int:
        return max(0, min(self.stock, MAX_LINE_QTY))

    @property
    def total(self) -> Decimal:
        return q2(self.item.line_total_override if self.item.line_total_override is not None else self.unit_price * self.qty)

    @property
    def label(self) -> str:
        return f"{self.variant.option_name}: {self.variant.option_value}" if self.variant else (self.product.pack_size or "")

    @property
    def sku(self) -> str:
        return self.variant.sku if self.variant else self.product.sku

    @property
    def image(self):
        return self.product.primary_image


def make_line(item: CartItem) -> Line:
    p, v = item.product, item.variant
    price, mrp = (v.price, v.mrp or v.price) if v is not None else (item.unit_price_override if item.unit_price_override is not None else p.final_price, p.mrp)
    stock = v.stock_qty if v is not None else p.stock_qty
    error = None
    if p.is_deleted or not p.is_active:
        error, stock = "No longer available", 0
    elif v is not None and (v.is_deleted or not v.is_active):
        error, stock = "This option is no longer available", 0
    elif v is None and active_variants(p):
        error, stock = "Choose an option on the product page", 0
    elif stock <= 0:
        error = "Out of stock"
    elif item.quantity > min(stock, MAX_LINE_QTY):
        error = f"Only {min(stock, MAX_LINE_QTY)} available. Lower the quantity."
    return Line(item=item, product=p, variant=v, unit_price=Decimal(price), mrp=Decimal(mrp), stock=stock, error=error, qty=item.quantity)


def load_items(owner, saved: bool) -> list[CartItem]:
    owner = as_owner(owner)
    return list(db.session.scalars(
        select(CartItem).where(owner.where(), CartItem.saved_for_later.is_(saved))
        .options(joinedload(CartItem.product).selectinload(Product.images), joinedload(CartItem.product).selectinload(Product.variants), joinedload(CartItem.variant))
        .order_by(CartItem.created_at.desc(), CartItem.id.desc())).unique())


def count_in_cart(owner) -> int:
    if owner is None:
        return 0
    owner = as_owner(owner)
    return db.session.scalar(select(func.coalesce(func.sum(CartItem.quantity), 0)).where(owner.where(), CartItem.saved_for_later.is_(False))) or 0


def free_delivery_threshold() -> Decimal:
    """Order value (after discounts) from which delivery is free. 0 = no free-delivery offer (the default).
    Set with: flask set-setting free_delivery_above 499"""
    v = money_setting("free_delivery_above", "0")
    return v if v > 0 else Decimal(0)


@dataclass
class Totals:
    subtotal: Decimal
    mrp_total: Decimal
    discount: Decimal
    delivery: Decimal | None      # None = not known until an address is chosen
    tax_included: Decimal
    total: Decimal

    @property
    def savings(self) -> Decimal:
        return self.mrp_total - self.subtotal + self.discount


def totals_for(lines: list[Line], discount: Decimal, zone: DeliveryZone | None) -> Totals:
    subtotal = q2(sum((l.total for l in lines), Decimal(0)))
    mrp_total = q2(sum((l.mrp * l.qty for l in lines), Decimal(0)))
    net = subtotal - discount
    delivery = None if zone is None else q2(Decimal(str(zone.delivery_fee or 0)))
    free_from = free_delivery_threshold()
    if delivery is not None and free_from > 0 and net >= free_from:
        delivery = q2(Decimal(0))
    rate = money_setting("tax_percent", "0")  # prices already include tax; this only shows how much of the bill it is
    tax = q2(net * rate / (Decimal(100) + rate)) if rate > 0 else Decimal(0)
    total = q2(net + (delivery if delivery is not None else Decimal(0)))
    return Totals(q2(subtotal), mrp_total, discount, delivery, tax, total)


@dataclass
class CartView:
    lines: list[Line]
    saved: list[Line]
    coupon: Coupon | None
    coupon_error: str | None
    totals: Totals
    problems: list[str] = field(default_factory=list)
    free_from: Decimal = Decimal(0)

    @property
    def net(self) -> Decimal:
        return self.totals.subtotal - self.totals.discount

    @property
    def free_remaining(self) -> Decimal:
        return max(Decimal(0), self.free_from - self.net) if self.free_from > 0 else Decimal(0)

    @property
    def free_pct(self) -> int:
        if self.free_from <= 0:
            return 0
        return int(min(Decimal(100), max(Decimal(0), self.net * 100 / self.free_from)))

    @property
    def count(self) -> int:
        return sum(l.qty for l in self.lines)

    @property
    def can_checkout(self) -> bool:
        return bool(self.lines) and not self.problems and not self.coupon_error


def build(owner, coupon_code: str | None = None, zone: DeliveryZone | None = None, only: list[CartItem] | None = None) -> CartView:
    """`owner` is a CartOwner, or a user id (kept so existing callers work). None builds an empty cart.
    `only` (the "Buy now" line) prices just those lines and ignores the saved cart completely."""
    if owner is None:
        empty = Totals(q2(0), q2(0), Decimal(0), None, Decimal(0), q2(0))
        return CartView([], [], None, None, empty, [], free_delivery_threshold())
    owner = as_owner(owner)
    user_id = owner.user_id
    lines = [make_line(i) for i in (only if only is not None else load_items(owner, False))]
    saved = [] if only is not None else [make_line(i) for i in load_items(owner, True)]
    subtotal = q2(sum((l.total for l in lines), Decimal(0)))
    coupon, err, discount = None, None, Decimal(0)
    if coupon_code and lines:
        coupon = coupons.find(coupon_code)
        try:
            if coupon is None:
                raise coupons.CouponError("That coupon code does not exist.")
            discount = coupons.discount_for(coupon, user_id, subtotal)
        except coupons.CouponError as e:
            err, discount = str(e), Decimal(0)
    problems = [f"{l.product.name}: {l.error}" for l in lines if l.error]
    return CartView(lines, saved, coupon, err, totals_for(lines, discount, zone), problems, free_delivery_threshold())
