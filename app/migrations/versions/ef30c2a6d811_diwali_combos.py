"""Add admin-managed festival combos."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "ef30c2a6d811"
down_revision = "b7f1c9a4d203"
branch_labels = None
depends_on = None

def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

def upgrade():
    op.create_table(
        "combos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("items", json_type(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("original_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("image", sa.String(500)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("festival_tag", sa.String(40), nullable=False, server_default="diwali"),
        sa.Column("bundle_id", sa.Integer(), sa.ForeignKey("bundles.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_combos_slug", "combos", ["slug"], unique=True)
    op.create_index("ix_combos_is_active", "combos", ["is_active"])
    op.create_index("ix_combos_festival_tag", "combos", ["festival_tag"])

def downgrade():
    op.drop_index("ix_combos_festival_tag", table_name="combos")
    op.drop_index("ix_combos_is_active", table_name="combos")
    op.drop_index("ix_combos_slug", table_name="combos")
    op.drop_table("combos")
