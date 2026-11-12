"""Phase 5: persistent login lockouts and browser push subscriptions.

Revision ID: 5d2e9a7c1f40
Revises: aa71c4e9d302, 1c4f8a9d302, 7a91c3e5d802
"""
from alembic import op
import sqlalchemy as sa

revision = "5d2e9a7c1f40"
down_revision = ("aa71c4e9d302", "1c4f8a9d2b70", "7a91c3e5d802")
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "login_lockouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scope", "subject_hash", name="uq_login_lockout_scope_subject"),
        sa.CheckConstraint("scope in ('account','ip')", name="ck_login_lockouts_scope"),
        sa.CheckConstraint("failed_count >= 0", name="ck_login_lockouts_failed_count"),
    )
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("endpoint", name="uq_push_subscription_endpoint"),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])

def downgrade():
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_table("login_lockouts")
