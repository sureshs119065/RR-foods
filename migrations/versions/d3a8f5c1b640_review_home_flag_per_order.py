"""reviews: 'show on home page' flag, and one review per order line instead of one per product

Revision ID: d3a8f5c1b640
Revises: c8f2a6d4e913
"""
from alembic import op
import sqlalchemy as sa

revision = "d3a8f5c1b640"
down_revision = "c8f2a6d4e913"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reviews") as b:
        b.add_column(sa.Column("show_on_home", sa.Boolean(), nullable=False, server_default=sa.false()))
        # A customer can now review the same product again for a later order, so the old (user, product) rule goes.
        b.drop_constraint("uq_reviews_user_product", type_="unique")
        b.create_unique_constraint("uq_reviews_user_order_item", ["user_id", "order_item_id"])


def downgrade():
    # Going back needs one review per (user, product): keep the newest and drop the rest, otherwise the old rule cannot be restored.
    op.execute(
        "DELETE FROM reviews WHERE id NOT IN (SELECT MAX(id) FROM reviews GROUP BY user_id, product_id)"
    )
    with op.batch_alter_table("reviews") as b:
        b.drop_constraint("uq_reviews_user_order_item", type_="unique")
        b.create_unique_constraint("uq_reviews_user_product", ["user_id", "product_id"])
        b.drop_column("show_on_home")
