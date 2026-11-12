from datetime import datetime, date

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import JsonType, SoftDeleteMixin, TimestampMixin, db


class Review(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_reviews_user_product"),
        CheckConstraint("rating between 1 and 5", name="ck_reviews_rating"),
        CheckConstraint("status in ('pending','approved','hidden')", name="ck_reviews_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_items.id", ondelete="SET NULL"))
    rating: Mapped[int] = mapped_column()
    title: Mapped[str | None] = mapped_column(String(150))
    body: Mapped[str | None] = mapped_column(Text)
    photos: Mapped[list] = mapped_column(JsonType, default=list)
    is_verified_purchase: Mapped[bool] = mapped_column(default=False, server_default="false")
    helpful_count: Mapped[int] = mapped_column(default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")

    user = relationship("User")


class ReviewVote(db.Model):
    __tablename__ = "review_votes"
    __table_args__ = (UniqueConstraint("review_id", "user_id", name="uq_review_votes"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class StockAlert(db.Model):
    """A customer asked to be told when an out-of-stock product is available again. notified_at is set once they were told."""
    __tablename__ = "stock_alerts"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_stock_alerts_user_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductQuestion(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "product_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(String(500))
    answer: Mapped[str | None] = mapped_column(Text)
    answered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InventoryLog(db.Model):
    """Every stock change: who, when, old and new quantity."""

    __tablename__ = "inventory_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id", ondelete="SET NULL"))
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    old_qty: Mapped[int] = mapped_column()
    new_qty: Mapped[int] = mapped_column()
    reason: Mapped[str | None] = mapped_column(String(200))  # manual edit, order placed, order cancelled, bulk update
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    product = relationship("Product")
    variant = relationship("ProductVariant")
    actor = relationship("User", foreign_keys=[changed_by])


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (CheckConstraint("channel in ('in_app','email')", name="ck_notifications_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(10), default="in_app", server_default="in_app")
    kind: Mapped[str] = mapped_column(String(40))  # order_status, low_stock, offer ...
    title: Mapped[str] = mapped_column(String(150))
    body: Mapped[str | None] = mapped_column(String(500))
    link: Mapped[str | None] = mapped_column(String(300))
    is_read: Mapped[bool] = mapped_column(default=False, server_default="false", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InventoryBatch(db.Model):
    """Traceable stock batch; Product.stock_qty remains the aggregate sellable quantity."""
    __tablename__ = "inventory_batches"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_inventory_batches_quantity_nonneg"),
        UniqueConstraint("product_id", "batch_number", name="uq_inventory_batch_product_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    batch_number: Mapped[str] = mapped_column(String(80))
    expiry_date: Mapped[date | None] = mapped_column(Date, index=True)
    quantity: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    product = relationship("Product")


class PushSubscription(db.Model):
    """Browser Push API endpoint owned by one customer; endpoint is unique per browser."""
    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("endpoint", name="uq_push_subscription_endpoint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    is_enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LoginLockout(db.Model):
    """Persistent per-account and per-IP lockout counters without storing raw identifiers."""
    __tablename__ = "login_lockouts"
    __table_args__ = (
        UniqueConstraint("scope", "subject_hash", name="uq_login_lockout_scope_subject"),
        CheckConstraint("scope in ('account','ip')", name="ck_login_lockouts_scope"),
        CheckConstraint("failed_count >= 0", name="ck_login_lockouts_failed_count"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(8))  # account | ip
    subject_hash: Mapped[str] = mapped_column(String(64))
    failed_count: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
