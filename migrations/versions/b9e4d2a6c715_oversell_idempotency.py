"""idempotency key and restore-once marker on orders

Revision ID: b9e4d2a6c715
Revises: a7d2c91e4b55
"""
from alembic import op
import sqlalchemy as sa

revision = "b9e4d2a6c715"
down_revision = "a7d2c91e4b55"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("idempotency_key", sa.String(length=64), nullable=True))
    op.add_column("orders", sa.Column("stock_restored_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_orders_idempotency_key", "orders", ["idempotency_key"])
    # Orders that took stock (they reached "placed") and were then rejected or cancelled already had it given back once.
    # Mark them so a late retry cannot give it back a second time. Never-confirmed requests took nothing, so they stay NULL.
    op.execute("""
        UPDATE orders o SET stock_restored_at = o.updated_at
        WHERE o.status IN ('rejected', 'cancelled')
          AND EXISTS (SELECT 1 FROM order_status_history h WHERE h.order_id = o.id AND h.to_status = 'placed')
    """)


def downgrade():
    op.drop_constraint("uq_orders_idempotency_key", "orders", type_="unique")
    op.drop_column("orders", "stock_restored_at")
    op.drop_column("orders", "idempotency_key")
