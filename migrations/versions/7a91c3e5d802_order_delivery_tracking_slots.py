"""Add optional courier tracking and delivery slot fields."""
from alembic import op
import sqlalchemy as sa

revision = "7a91c3e5d802"
down_revision = "5e1b8d3f7a92"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("orders", sa.Column("courier_name", sa.String(length=120), nullable=True))
    op.add_column("orders", sa.Column("tracking_id", sa.String(length=120), nullable=True))
    op.add_column("orders", sa.Column("tracking_url", sa.String(length=500), nullable=True))
    op.add_column("orders", sa.Column("delivery_date", sa.Date(), nullable=True))
    op.add_column("orders", sa.Column("delivery_slot", sa.String(length=20), nullable=True))
    op.create_index("ix_orders_delivery_slot", "orders", ["delivery_date", "delivery_slot", "status"], unique=False)
    op.add_column("delivery_zones", sa.Column("city", sa.String(length=80), nullable=True))
    op.add_column("delivery_zones", sa.Column("state", sa.String(length=80), nullable=True))
    settings = sa.table("site_settings", sa.column("key", sa.String(length=80)), sa.column("value", sa.JSON()))
    op.bulk_insert(settings, [{"key": "delivery_slot_settings", "value": {"cutoff_time": "14:00", "max_orders_per_slot": 20, "blocked_dates": [], "days_ahead": 7}}])
    op.execute("DELETE FROM site_settings WHERE key = 'free_delivery_min_cart'")
    op.execute("DELETE FROM header_banners WHERE lower(title) = 'free delivery'")

def downgrade():
    op.execute("DELETE FROM site_settings WHERE key = 'delivery_slot_settings'")
    op.drop_column("delivery_zones", "state")
    op.drop_column("delivery_zones", "city")
    op.drop_index("ix_orders_delivery_slot", table_name="orders")
    op.drop_column("orders", "delivery_slot")
    op.drop_column("orders", "delivery_date")
    op.drop_column("orders", "tracking_url")
    op.drop_column("orders", "tracking_id")
    op.drop_column("orders", "courier_name")
