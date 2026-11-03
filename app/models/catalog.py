from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Table, Column, Text, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import JsonType, Money, SoftDeleteMixin, TimestampMixin, db, q2

DISCOUNT_TYPES = ("none", "percent", "flat")


class Category(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("slug", name="uq_categories_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140))
    description: Mapped[str | None] = mapped_column(Text)
    image: Mapped[str | None] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    parent = relationship("Category", remote_side="Category.id", backref="children")


product_offers = Table(
    "product_offers", db.metadata,
    Column("product_id", ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("offer_id", ForeignKey("offers.id", ondelete="CASCADE"), primary_key=True),
)

product_related = Table(
    "product_related", db.metadata,
    Column("product_id", ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("related_id", ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    CheckConstraint("product_id <> related_id", name="ck_product_related_self"),
)


class Product(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_products_slug"),
        UniqueConstraint("sku", name="uq_products_sku"),
        CheckConstraint("mrp >= 0", name="ck_products_mrp_nonneg"),
        CheckConstraint("final_price >= 0", name="ck_products_final_nonneg"),
        CheckConstraint("stock_qty >= 0", name="ck_products_stock_nonneg"),
        CheckConstraint("discount_type in ('none','percent','flat')", name="ck_products_discount_type"),
        CheckConstraint(
            "(discount_type <> 'percent' or (discount_value >= 0 and discount_value <= 100))"
            " and (discount_type <> 'flat' or discount_value >= 0)",
            name="ck_products_discount_range",
        ),
        Index("ix_products_category_price", "category_id", "final_price"),
        Index("ix_products_listing", "is_active", "is_deleted"),
        Index("ix_products_name_lower", text("lower(name)")),
        # Full-text search and typo-tolerant (trigram) search. The pg_trgm extension is created in the migration.
        Index(
            "ix_products_fts",
            text("to_tsvector('simple', coalesce(name,'') || ' ' || coalesce(brand,'') || ' ' || coalesce(short_description,''))"),
            postgresql_using="gin",
        ),
        Index("ix_products_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(60))
    slug: Mapped[str] = mapped_column(String(180))
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str | None] = mapped_column(String(120), index=True)
    short_description: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    subcategory_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    pack_size: Mapped[str | None] = mapped_column(String(40))

    mrp: Mapped[Decimal] = mapped_column(Money)
    discount_type: Mapped[str] = mapped_column(String(8), default="none", server_default="none")
    discount_value: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    final_price: Mapped[Decimal] = mapped_column(Money)

    stock_qty: Mapped[int] = mapped_column(default=0, server_default="0")
    low_stock_threshold: Mapped[int] = mapped_column(default=5, server_default="5")
    tags: Mapped[list] = mapped_column(JsonType, default=list)
    specifications: Mapped[dict] = mapped_column(JsonType, default=dict)
    ingredients: Mapped[str | None] = mapped_column(Text)
    nutrition: Mapped[dict] = mapped_column(JsonType, default=dict)
    how_to_use: Mapped[str | None] = mapped_column(Text)
    fssai: Mapped[str | None] = mapped_column(String(30))
    video_id: Mapped[str | None] = mapped_column(String(20))

    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    is_bestseller: Mapped[bool] = mapped_column(default=False, server_default="false")
    avg_rating: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    review_count: Mapped[int] = mapped_column(default=0, server_default="0")
    sales_count: Mapped[int] = mapped_column(default=0, server_default="0", index=True)

    category = relationship("Category", foreign_keys=[category_id])
    subcategory = relationship("Category", foreign_keys=[subcategory_id])
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.sort_order")
    variants = relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan")
    offers = relationship("Offer", secondary=product_offers, back_populates="products")
    related = relationship(
        "Product", secondary=product_related,
        primaryjoin="Product.id == product_related.c.product_id",
        secondaryjoin="Product.id == product_related.c.related_id",
    )

    # --- pricing -------------------------------------------------------
    def compute_final_price(self) -> Decimal:
        mrp = Decimal(self.mrp)
        value = Decimal(self.discount_value or 0)
        if self.discount_type == "percent":
            price = mrp * (Decimal(100) - value) / Decimal(100)
        elif self.discount_type == "flat":
            price = mrp - value
        else:
            price = mrp
        return max(price, Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def apply_pricing(self) -> None:
        """Call after changing mrp or the discount. Keeps final_price in sync."""
        self.final_price = self.compute_final_price()

    @property
    def discount_percent(self) -> int:
        if not self.mrp or Decimal(self.mrp) == 0 or self.final_price >= self.mrp:
            return 0
        return int(((Decimal(self.mrp) - Decimal(self.final_price)) / Decimal(self.mrp) * 100).to_integral_value(ROUND_HALF_UP))

    @property
    def is_low_stock(self) -> bool:
        return 0 < self.stock_qty <= self.low_stock_threshold

    @property
    def primary_image(self):
        for img in self.images:
            if img.is_primary:
                return img
        return self.images[0] if self.images else None


class ProductImage(TimestampMixin, db.Model):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(500))
    thumb_url: Mapped[str | None] = mapped_column(String(500))
    alt: Mapped[str | None] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")
    is_primary: Mapped[bool] = mapped_column(default=False, server_default="false")

    product = relationship("Product", back_populates="images")


class ProductVariant(TimestampMixin, SoftDeleteMixin, db.Model):
    """Size / colour / weight option with its own stock and price."""

    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_variants_sku"),
        CheckConstraint("stock_qty >= 0", name="ck_variants_stock_nonneg"),
        CheckConstraint("price >= 0", name="ck_variants_price_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    option_name: Mapped[str] = mapped_column(String(40))  # e.g. Size, Colour, Weight
    option_value: Mapped[str] = mapped_column(String(80))  # e.g. 500 g
    sku: Mapped[str] = mapped_column(String(60))
    mrp: Mapped[Decimal | None] = mapped_column(Money)
    price: Mapped[Decimal] = mapped_column(Money)
    stock_qty: Mapped[int] = mapped_column(default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    product = relationship("Product", back_populates="variants")


class Offer(TimestampMixin, db.Model):
    """Labels such as "Deal of the Day" or "Buy 1 Get 1", attached to products."""

    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    tag: Mapped[str] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(String(300))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    products = relationship("Product", secondary=product_offers, back_populates="offers")


class Coupon(TimestampMixin, db.Model):
    __tablename__ = "coupons"
    __table_args__ = (
        CheckConstraint("discount_type in ('percent','flat')", name="ck_coupons_type"),
        CheckConstraint("discount_value > 0", name="ck_coupons_value_pos"),
        CheckConstraint("discount_type <> 'percent' or discount_value <= 100", name="ck_coupons_percent_max"),
        Index("uq_coupons_code_upper", text("upper(code)"), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(String(200))
    discount_type: Mapped[str] = mapped_column(String(8))
    discount_value: Mapped[Decimal] = mapped_column(Money)
    max_discount: Mapped[Decimal | None] = mapped_column(Money)
    min_cart_value: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage_limit: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(default=0, server_default="0")
    per_user_limit: Mapped[int] = mapped_column(default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class CouponUsage(db.Model):
    __tablename__ = "coupon_usages"

    id: Mapped[int] = mapped_column(primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
