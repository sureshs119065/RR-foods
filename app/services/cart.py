"""Cart lines, availability and the price breakdown. Prices always come from the database, never from the browser."""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from ..extensions import db
from ..models import CartItem, Coupon, DeliveryZone, Product, ProductVariant
from . import coupons
from .storefront import active_variants, money_setting

MAX_LINE_QTY = 10
TWO = Decimal("0.01")


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


def load_items(user_id: int, saved: bool) -> list[CartItem]:
    return list(db.session.scalars(
        select(CartItem).where(CartItem.user_id == user_id, CartItem.saved_for_later.is_(saved))
        .options(joinedload(CartItem.product).selectinload(Product.images), joinedload(CartItem.product).selectinload(Product.variants), joinedload(CartItem.variant))
        .order_by(CartItem.created_at.desc(), CartItem.id.desc())).unique())


def count_in_cart(user_id: int) -> int:
    from sqlalchemy import func
    return db.session.scalar(select(func.coalesce(func.sum(CartItem.quantity), 0)).where(CartItem.user_id == user_id, CartItem.saved_for_later.is_(False))) or 0


@dataclass
class Totals:
    subtotal: Decimal
    mrp_total: Decimal
    discount: Decimal
    delivery: Decimal | None      # None = not known until an address is chosen
    tax_included: Decimal
    total: Decimal
    free_min: Decimal
    free_gap: Decimal             # how much more to spend for free delivery (0 when already free or no threshold)

    @property
    def savings(self) -> Decimal:
        return self.mrp_total - self.subtotal + self.discount


def totals_for(lines: list[Line], discount: Decimal, zone: DeliveryZone | None) -> Totals:
    subtotal = q2(sum((l.total for l in lines), Decimal(0)))
    mrp_total = q2(sum((l.mrp * l.qty for l in lines), Decimal(0)))
    net = subtotal - discount
    free_min = money_setting("free_delivery_min_cart", "0")
    free = free_min > 0 and net >= free_min
    delivery = None if zone is None else (Decimal(0) if free else q2(Decimal(str(zone.delivery_fee or 0))))
    rate = money_setting("tax_percent", "0")  # prices already include tax; this only shows how much of the bill it is
    tax = q2(net * rate / (Decimal(100) + rate)) if rate > 0 else Decimal(0)
    total = q2(net + (delivery if delivery is not None else Decimal(0)))
    gap = q2(free_min - net) if free_min > 0 and not free else Decimal(0)
    return Totals(q2(subtotal), mrp_total, discount, delivery if delivery is not None or zone is None else delivery, tax, total, free_min, gap)


@dataclass
class CartView:
    lines: list[Line]
    saved: list[Line]
    coupon: Coupon | None
    coupon_error: str | None
    totals: Totals
    problems: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return sum(l.qty for l in self.lines)

    @property
    def can_checkout(self) -> bool:
        return bool(self.lines) and not self.problems and not self.coupon_error


def build(user_id: int, coupon_code: str | None = None, zone: DeliveryZone | None = None) -> CartView:
    lines = [make_line(i) for i in load_items(user_id, False)]
    saved = [make_line(i) for i in load_items(user_id, True)]
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
    return CartView(lines, saved, coupon, err, totals_for(lines, discount, zone), problems)
