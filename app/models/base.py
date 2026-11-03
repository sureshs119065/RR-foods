from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db

# JSON on any database, JSONB (indexable) on PostgreSQL.
JsonType = JSON().with_variant(JSONB(), "postgresql")
Money = Numeric(10, 2)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow
    )


class SoftDeleteMixin:
    """Rows are archived, not removed. Permanent delete is a separate, confirmed admin action."""

    is_deleted: Mapped[bool] = mapped_column(default=False, server_default="false", index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def archive(self) -> None:
        self.is_deleted = True
        self.deleted_at = utcnow()

    def restore(self) -> None:
        self.is_deleted = False
        self.deleted_at = None


def q2(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


__all__ = ["db", "JsonType", "Money", "TimestampMixin", "SoftDeleteMixin", "utcnow", "q2"]
