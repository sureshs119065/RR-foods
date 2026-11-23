"""Email one-time codes for customer sign-in.

Revision ID: a7d2c91e4b55
Revises: e8c4f6b2d103
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = "a7d2c91e4b55"
down_revision = "e8c4f6b2d103"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_otp",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("otp_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_used", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
    )
    op.create_index("ix_email_otp_email", "email_otp", ["email"])
    op.create_index("ix_email_otp_expires_at", "email_otp", ["expires_at"])
    op.create_index("ix_email_otp_ip_address", "email_otp", ["ip_address"])
    op.create_index("ix_email_otp_email_created", "email_otp", ["email", "created_at"])


def downgrade():
    op.drop_index("ix_email_otp_email_created", table_name="email_otp")
    op.drop_index("ix_email_otp_ip_address", table_name="email_otp")
    op.drop_index("ix_email_otp_expires_at", table_name="email_otp")
    op.drop_index("ix_email_otp_email", table_name="email_otp")
    op.drop_table("email_otp")
