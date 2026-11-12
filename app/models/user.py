from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import SoftDeleteMixin, TimestampMixin, db

ROLES = ("user", "owner", "admin")


class User(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role in ('user','owner','admin')", name="ck_users_role"),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default="user", server_default="user", index=True)
    is_blocked: Mapped[bool] = mapped_column(default=False, server_default="false")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wallet_points: Mapped[int] = mapped_column(default=0, server_default="0")
    failed_login_count: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User {self.email} {self.role}>"


class Address(TimestampMixin, db.Model):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(40), default="Home")
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    line1: Mapped[str] = mapped_column(String(200))
    line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(80))
    pincode: Mapped[str] = mapped_column(String(10), index=True)
    is_default: Mapped[bool] = mapped_column(default=False, server_default="false")

    user = relationship("User", back_populates="addresses")


class DeliveryZone(db.Model):
    """Pincode check on the product page and delivery fee/ETA at checkout."""

    __tablename__ = "delivery_zones"

    pincode: Mapped[str] = mapped_column(String(10), primary_key=True)
    is_serviceable: Mapped[bool] = mapped_column(default=True, server_default="true")
    eta_days: Mapped[int] = mapped_column(default=3, server_default="3")
    delivery_fee: Mapped[float] = mapped_column(default=0, server_default="0")
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(80))
