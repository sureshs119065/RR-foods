"""Add back-in-stock alerts (customers asking to be told when a product is available again).

Revision ID: 5e1b8d3f7a92
Revises: 3a7c9e21d4b6
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa

revision = "5e1b8d3f7a92"
down_revision = "3a7c9e21d4b6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stock_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "product_id", name="uq_stock_alerts_user_product"),
    )
    op.create_index("ix_stock_alerts_user_id", "stock_alerts", ["user_id"])
    op.create_index("ix_stock_alerts_product_id", "stock_alerts", ["product_id"])


def downgrade():
    op.drop_index("ix_stock_alerts_product_id", table_name="stock_alerts")
    op.drop_index("ix_stock_alerts_user_id", table_name="stock_alerts")
    op.drop_table("stock_alerts")
