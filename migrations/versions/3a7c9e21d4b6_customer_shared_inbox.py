"""Add customer-to-staff shared inbox conversations.

Revision ID: 3a7c9e21d4b6
Revises: 0b0d5552b3f8
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa

revision = "3a7c9e21d4b6"
down_revision = "0b0d5552b3f8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_message_threads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_customer_message_threads_user_id", "customer_message_threads", ["user_id"])
    op.create_index("ix_customer_message_threads_status", "customer_message_threads", ["status"])
    op.create_index("ix_customer_message_threads_last_message_at", "customer_message_threads", ["last_message_at"])
    op.create_table(
        "customer_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("customer_message_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_customer_messages_thread_id", "customer_messages", ["thread_id"])
    op.create_index("ix_customer_messages_sender_id", "customer_messages", ["sender_id"])


def downgrade():
    op.drop_index("ix_customer_messages_sender_id", table_name="customer_messages")
    op.drop_index("ix_customer_messages_thread_id", table_name="customer_messages")
    op.drop_table("customer_messages")
    op.drop_index("ix_customer_message_threads_last_message_at", table_name="customer_message_threads")
    op.drop_index("ix_customer_message_threads_status", table_name="customer_message_threads")
    op.drop_index("ix_customer_message_threads_user_id", table_name="customer_message_threads")
    op.drop_table("customer_message_threads")
