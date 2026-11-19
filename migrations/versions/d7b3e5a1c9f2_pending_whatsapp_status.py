"""add the pending_whatsapp order status (checkout request that is not an order until the WhatsApp message reaches the shop)

Revision ID: d7b3e5a1c9f2
Revises: 6b3d8f1a4c72
Create Date: 2026-11-19 10:00:00
"""
from alembic import op

revision = "d7b3e5a1c9f2"
down_revision = "6b3d8f1a4c72"
branch_labels = None
depends_on = None

OLD = "'placed','confirmed','rejected','packed','shipped','out_for_delivery','delivered','cancelled','return_requested','returned','refunded'"
NEW = "'pending_whatsapp'," + OLD


def _swap(statuses: str) -> None:
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.create_check_constraint("ck_orders_status", "orders", f"status in ({statuses})")



def upgrade():
    _swap(NEW)


def downgrade():
    # a pending request was never an order: nothing was taken from stock for it, so it can simply be closed
    op.execute("update orders set status = 'cancelled' where status = 'pending_whatsapp'")
    _swap(OLD)
