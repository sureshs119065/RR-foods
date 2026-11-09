"""add the out_for_delivery order status

Revision ID: c5a2d9e81f47
Revises: ef30c2a6d811
Create Date: 2026-11-03 09:00:00
"""
from alembic import op

revision = "c5a2d9e81f47"
down_revision = "ef30c2a6d811"
branch_labels = None
depends_on = None

OLD = "'placed','confirmed','rejected','packed','shipped','delivered','cancelled','return_requested','returned','refunded'"
NEW = "'placed','confirmed','rejected','packed','shipped','out_for_delivery','delivered','cancelled','return_requested','returned','refunded'"


def _swap(statuses: str) -> None:
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.create_check_constraint("ck_orders_status", "orders", f"status in ({statuses})")


def upgrade():
    _swap(NEW)


def downgrade():
    op.execute("update orders set status = 'shipped' where status = 'out_for_delivery'")
    _swap(OLD)
