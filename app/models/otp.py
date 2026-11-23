from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import db


class EmailOtp(db.Model):
    """One emailed sign-in code. Only a keyed hash of the code is stored, never the code itself."""

    __tablename__ = "email_otp"
    __table_args__ = (Index("ix_email_otp_email_created", "email", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    otp_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    is_used: Mapped[bool] = mapped_column(default=False, server_default="false")
    ip_address: Mapped[str | None] = mapped_column(String(45), index=True)
