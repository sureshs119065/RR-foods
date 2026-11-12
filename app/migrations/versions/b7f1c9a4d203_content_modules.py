"""Add reels, recipe videos and product bundles."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7f1c9a4d203"
down_revision = "dcef60c4798e"
branch_labels = None
depends_on = None

def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

def upgrade():
    op.drop_index("uq_cart_user_product_variant", table_name="cart_items")
    op.add_column("cart_items", sa.Column("bundle_id", sa.Integer(), nullable=True))
    op.add_column("cart_items", sa.Column("unit_price_override", sa.Numeric(10, 2), nullable=True))
    op.add_column("cart_items", sa.Column("line_total_override", sa.Numeric(10, 2), nullable=True))
    op.create_table(
        "reels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("video_url", sa.String(500), nullable=False),
        sa.Column("thumbnail_url", sa.String(500)),
        sa.Column("linked_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_reels_is_active", "reels", ["is_active"])
    op.create_index("ix_reels_sort_order", "reels", ["sort_order"])
    op.create_table(
        "recipe_videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("video_url", sa.String(500)),
        sa.Column("youtube_url", sa.String(500)),
        sa.Column("thumbnail_url", sa.String(500)),
        sa.Column("category", sa.String(100)),
        sa.Column("ingredients", json_type(), nullable=False),
        sa.Column("linked_product_ids", json_type(), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_recipe_videos_slug", "recipe_videos", ["slug"], unique=True)
    op.create_index("ix_recipe_videos_category", "recipe_videos", ["category"])
    op.create_index("ix_recipe_videos_is_published", "recipe_videos", ["is_published"])
    op.create_table(
        "bundles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("image_url", sa.String(500)),
        sa.Column("product_quantities", json_type(), nullable=False),
        sa.Column("bundle_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bundles_slug", "bundles", ["slug"], unique=True)
    op.create_index("ix_bundles_is_active", "bundles", ["is_active"])
    op.create_foreign_key("fk_cart_items_bundle_id_bundles", "cart_items", "bundles", ["bundle_id"], ["id"], ondelete="CASCADE")
    op.create_index("uq_cart_user_product_variant", "cart_items", ["user_id", "product_id", sa.text("coalesce(variant_id, 0)"), sa.text("coalesce(bundle_id, 0)")], unique=True)

def downgrade():
    op.drop_index("uq_cart_user_product_variant", table_name="cart_items")
    op.drop_constraint("fk_cart_items_bundle_id_bundles", "cart_items", type_="foreignkey")
    op.drop_column("cart_items", "line_total_override")
    op.drop_column("cart_items", "unit_price_override")
    op.drop_column("cart_items", "bundle_id")
    op.create_index("uq_cart_user_product_variant", "cart_items", ["user_id", "product_id", sa.text("coalesce(variant_id, 0)")], unique=True)
    op.drop_table("bundles")
    op.drop_table("recipe_videos")
    op.drop_table("reels")
