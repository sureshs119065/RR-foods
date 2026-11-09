"""Add the out_for_delivery order status."""
from alembic import op

revision = "c4e8a1d7f5b2"
down_revision = "ef30c2a6d811"
branch_labels = None
depends_on = None

OLD = "status in ('placed','confirmed','rejected','packed','shipped','delivered','cancelled','return_requested','returned','refunded')"
NEW = "status in ('placed','confirmed','rejected','packed','shipped','out_for_delivery','delivered','cancelled','return_requested','returned','refunded')"


def upgrade():
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.create_check_constraint("ck_orders_status", "orders", NEW)


def downgrade():
    op.execute("UPDATE orders SET status = 'shipped' WHERE status = 'out_for_delivery'")
    op.execute("UPDATE order_status_history SET to_status = 'shipped' WHERE to_status = 'out_for_delivery'")
    op.execute("UPDATE order_status_history SET from_status = 'shipped' WHERE from_status = 'out_for_delivery'")
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.create_check_constraint("ck_orders_status", "orders", OLD)
