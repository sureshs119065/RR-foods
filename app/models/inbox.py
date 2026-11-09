from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import TimestampMixin, db


class CustomerMessageThread(TimestampMixin, db.Model):
    __tablename__ = "customer_message_threads"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open", index=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    customer = relationship("User", foreign_keys=[user_id])
    messages = relationship("CustomerMessage", back_populates="thread", cascade="all, delete-orphan", order_by="CustomerMessage.created_at")


class CustomerMessage(TimestampMixin, db.Model):
    __tablename__ = "customer_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("customer_message_threads.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    sender = relationship("User", foreign_keys=[sender_id])
    thread = relationship("CustomerMessageThread", back_populates="messages")
