"""guest cart: cart_items.session_id, nullable user_id, owner CHECK

Revision ID: 6b3d8f1a4c72
Revises: 5d2e9a7c1f40
"""
import sqlalchemy as sa
from alembic import op

revision = "6b3d8f1a4c72"
down_revision = "5d2e9a7c1f40"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cart_items", sa.Column("session_id", sa.String(length=64), nullable=True))
    op.alter_column("cart_items", "user_id", existing_type=sa.Integer(), nullable=True)
    op.create_index("ix_cart_items_session_id", "cart_items", ["session_id"])
    op.create_index("uq_cart_session_product_variant", "cart_items",
                    ["session_id", "product_id", sa.text("coalesce(variant_id, 0)"), sa.text("coalesce(bundle_id, 0)")], unique=True)
    op.create_check_constraint("ck_cart_owner_set", "cart_items", "user_id IS NOT NULL OR session_id IS NOT NULL")


def downgrade():
    op.drop_constraint("ck_cart_owner_set", "cart_items", type_="check")
    op.execute("DELETE FROM cart_items WHERE user_id IS NULL")  # guest rows cannot exist without the column
    op.drop_index("uq_cart_session_product_variant", table_name="cart_items")
    op.drop_index("ix_cart_items_session_id", table_name="cart_items")
    op.alter_column("cart_items", "user_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("cart_items", "session_id")
