"""Add delivered timestamp to orders."""
from alembic import op
import sqlalchemy as sa

revision = "f4a91d7c2e10"
down_revision = "c4e8a1d7f5b2"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("orders", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column("orders", "delivered_at")
