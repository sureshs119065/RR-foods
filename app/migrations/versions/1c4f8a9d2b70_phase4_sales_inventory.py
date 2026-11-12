"""Phase 4 sales insights and inventory batches

Revision ID: 1c4f8a9d2b70
Revises: 5e1b8d3f7a92
Create Date: 2026-11-12
"""
from alembic import op
import sqlalchemy as sa

revision = "1c4f8a9d2b70"
down_revision = "5e1b8d3f7a92"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("products", sa.Column("reorder_level", sa.Integer(), server_default="5", nullable=False))
    op.create_check_constraint("ck_products_reorder_level_nonneg", "products", "reorder_level >= 0")
    op.create_table(
        "inventory_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_number", sa.String(80), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_inventory_batches_quantity_nonneg"),
        sa.UniqueConstraint("product_id", "batch_number", name="uq_inventory_batch_product_number"),
    )
    op.create_index("ix_inventory_batches_product_id", "inventory_batches", ["product_id"])
    op.create_index("ix_inventory_batches_expiry_date", "inventory_batches", ["expiry_date"])

def downgrade():
    op.drop_index("ix_inventory_batches_expiry_date", table_name="inventory_batches")
    op.drop_index("ix_inventory_batches_product_id", table_name="inventory_batches")
    op.drop_table("inventory_batches")
    op.drop_constraint("ck_products_reorder_level_nonneg", "products", type_="check")
    op.drop_column("products", "reorder_level")
