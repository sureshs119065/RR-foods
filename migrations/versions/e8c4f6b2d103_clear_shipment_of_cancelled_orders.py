"""remove courier, tracking and delivery date from orders that were cancelled or rejected (they are never shipped)

Revision ID: e8c4f6b2d103
Revises: d7b3e5a1c9f2
Create Date: 2026-11-19 12:00:00
"""
from alembic import op

revision = "e8c4f6b2d103"
down_revision = "d7b3e5a1c9f2"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("update orders set courier_name = null, tracking_id = null, tracking_url = null, delivery_date = null, delivery_slot = null "
               "where status in ('cancelled', 'rejected', 'pending_whatsapp')")


def downgrade():
    pass  # the removed details described shipments that never happened
