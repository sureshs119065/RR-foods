from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import JsonType, Money, TimestampMixin, db

# Tracking timeline: placed -> confirmed -> packed -> shipped -> out_for_delivery -> delivered
ORDER_STATUSES = (
    "placed", "confirmed", "rejected", "packed", "shipped", "out_for_delivery", "delivered",
    "cancelled", "return_requested", "returned", "refunded",
)
PAYMENT_METHODS = ("cod", "online", "upi_manual")
PAYMENT_STATUSES = ("pending", "paid", "failed", "refunded")

_status_list = ",".join(f"'{s}'" for s in ORDER_STATUSES)


class CartItem(TimestampMixin, db.Model):
    __tablename__ = "cart_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_cart_qty_pos"),
        # one row per user + product + variant (variant may be empty)
        Index("uq_cart_user_product_variant", "user_id", "product_id", text("coalesce(variant_id, 0)"), text("coalesce(bundle_id, 0)"), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id", ondelete="CASCADE"))
    bundle_id: Mapped[int | None] = mapped_column(ForeignKey("bundles.id", ondelete="CASCADE"))
    unit_price_override: Mapped[Decimal | None] = mapped_column(Money)
    line_total_override: Mapped[Decimal | None] = mapped_column(Money)
    quantity: Mapped[int] = mapped_column(default=1, server_default="1")
    saved_for_later: Mapped[bool] = mapped_column(default=False, server_default="false")

    product = relationship("Product")
    variant = relationship("ProductVariant")
    bundle = relationship("Bundle")


class WishlistItem(db.Model):
    __tablename__ = "wishlist"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_wishlist_user_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product")


class Order(TimestampMixin, db.Model):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_number", name="uq_orders_number"),
        CheckConstraint(f"status in ({_status_list})", name="ck_orders_status"),
        CheckConstraint("payment_method in ('cod','online','upi_manual')", name="ck_orders_pay_method"),
        CheckConstraint("payment_status in ('pending','paid','failed','refunded')", name="ck_orders_pay_status"),
        CheckConstraint("total >= 0 and subtotal >= 0", name="ck_orders_amounts"),
        Index("ix_orders_user_created", "user_id", "created_at"),
        Index("ix_orders_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(30))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="placed", server_default="placed")
    rejection_reason: Mapped[str | None] = mapped_column(String(300))
    shipping_address: Mapped[dict] = mapped_column(JsonType)  # snapshot, so later edits do not change old orders
    subtotal: Mapped[Decimal] = mapped_column(Money)
    discount_total: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    delivery_fee: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    total: Mapped[Decimal] = mapped_column(Money)
    coupon_id: Mapped[int | None] = mapped_column(ForeignKey("coupons.id", ondelete="SET NULL"))
    coupon_code: Mapped[str | None] = mapped_column(String(40))
    payment_method: Mapped[str] = mapped_column(String(12), default="cod", server_default="cod")
    payment_status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    customer_notes: Mapped[str | None] = mapped_column(Text)

    user = relationship("User")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    history = relationship("OrderStatusHistory", back_populates="order", cascade="all, delete-orphan", order_by="OrderStatusHistory.created_at")
    payments = relationship("Payment", back_populates="order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_order_items_qty_pos"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id", ondelete="SET NULL"))
    # Snapshots keep invoices correct even if the product is edited or archived later.
    name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str | None] = mapped_column(String(60))
    pack_size: Mapped[str | None] = mapped_column(String(80))
    unit_price: Mapped[Decimal] = mapped_column(Money)
    mrp: Mapped[Decimal] = mapped_column(Money)
    quantity: Mapped[int] = mapped_column()
    line_total: Mapped[Decimal] = mapped_column(Money)

    order = relationship("Order", back_populates="items")


class OrderStatusHistory(db.Model):
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="history")


class Payment(TimestampMixin, db.Model):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount >= 0", name="ck_payments_amount"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))  # cod | razorpay | upi_manual
    provider_ref: Mapped[str | None] = mapped_column(String(100), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    raw: Mapped[dict | None] = mapped_column(JsonType)

    order = relationship("Order", back_populates="payments")
