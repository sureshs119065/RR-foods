from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import JsonType, TimestampMixin, db


class Banner(TimestampMixin, db.Model):
    """Home page sections other than the header carousel: hero slider, featured categories, deals strip."""

    __tablename__ = "banners"
    __table_args__ = (CheckConstraint("section in ('hero','featured_categories','deals_strip')", name="ck_banners_section"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    section: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(150))
    subtitle: Mapped[str | None] = mapped_column(String(250))
    image: Mapped[str | None] = mapped_column(String(500))
    link_url: Mapped[str | None] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HeaderBanner(TimestampMixin, db.Model):
    """Header offer carousel on the main dashboard (admin managed, scheduled)."""

    __tablename__ = "header_banners"
    __table_args__ = (
        CheckConstraint("link_type in ('category','product','coupon','url')", name="ck_header_banners_link_type"),
        CheckConstraint("end_at is null or start_at is null or end_at > start_at", name="ck_header_banners_window"),
        Index("ix_header_banners_active_order", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    subtitle: Mapped[str | None] = mapped_column(String(250))
    badge_text: Mapped[str | None] = mapped_column(String(40))
    desktop_image: Mapped[str | None] = mapped_column(String(500))
    mobile_image: Mapped[str | None] = mapped_column(String(500))
    bg_color: Mapped[str] = mapped_column(String(9), default="#1b5e3b", server_default="#1b5e3b")
    text_color: Mapped[str] = mapped_column(String(9), default="#ffffff", server_default="#ffffff")
    button_text: Mapped[str | None] = mapped_column(String(40))
    link_type: Mapped[str] = mapped_column(String(10), default="url", server_default="url")
    link_target: Mapped[str | None] = mapped_column(String(500))
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    countdown_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class SiteSetting(db.Model):
    """Key/value settings edited in admin (carousel interval, delivery threshold, tax, ...)."""

    __tablename__ = "site_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JsonType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(60))  # product.create, banner.delete, user.block ...
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    before: Mapped[dict | None] = mapped_column(JsonType)
    after: Mapped[dict | None] = mapped_column(JsonType)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    actor = relationship("User", foreign_keys=[actor_id])


class Reel(TimestampMixin, db.Model):
    """Short product video displayed only in the home-page reels rail."""
    __tablename__ = "reels"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    video_url: Mapped[str] = mapped_column(String(500))
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    linked_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true", index=True)
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0", index=True)
    product = relationship("Product")


class RecipeVideo(TimestampMixin, db.Model):
    """Published cooking recipe with either an uploaded video or a YouTube URL."""
    __tablename__ = "recipe_videos"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    name_ta: Mapped[str | None] = mapped_column(String(180))
    description_ta: Mapped[str | None] = mapped_column(Text)
    video_url: Mapped[str | None] = mapped_column(String(500))
    youtube_url: Mapped[str | None] = mapped_column(String(500))
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    ingredients: Mapped[list] = mapped_column(JsonType, default=list)
    linked_product_ids: Mapped[list] = mapped_column(JsonType, default=list)
    is_published: Mapped[bool] = mapped_column(default=False, server_default="false", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Bundle(TimestampMixin, db.Model):
    """A curated group of existing products with a fixed bundle price."""
    __tablename__ = "bundles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(500))
    product_quantities: Mapped[list] = mapped_column(JsonType, default=list)
    bundle_price: Mapped[float] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true", index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Combo(TimestampMixin, db.Model):
    """Admin-managed festival combo, linked to a Bundle for discounted cart pricing."""
    __tablename__ = "combos"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    items: Mapped[list] = mapped_column(JsonType, default=list)
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    original_price: Mapped[float] = mapped_column(Numeric(10, 2))
    image: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true", index=True)
    festival_tag: Mapped[str] = mapped_column(String(40), default="diwali", server_default="diwali", index=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id", ondelete="CASCADE"), unique=True)
    bundle = relationship("Bundle")


class PointsLedger(db.Model):
    __tablename__ = "points_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), index=True)
    points: Mapped[int] = mapped_column()
    entry_type: Mapped[str] = mapped_column(String(12))
    reason: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class SearchTerm(db.Model):
    __tablename__ = "search_terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

class RecipeFavourite(db.Model):
    __tablename__ = "recipe_favourites"
    __table_args__ = (db.UniqueConstraint("user_id", "recipe_id", name="uq_recipe_favourite"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe_videos.id", ondelete="CASCADE"), index=True)
