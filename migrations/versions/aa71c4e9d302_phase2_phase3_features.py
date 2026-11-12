"""Phase 2/3 sharing, loyalty, language and gift fields."""
from alembic import op
import sqlalchemy as sa
revision = "aa71c4e9d302"
down_revision = "f4a91d7c2e10"
branch_labels = None
depends_on = None
def upgrade():
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("referral_code", sa.String(16), nullable=True))
        b.add_column(sa.Column("referred_by_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("preferred_language", sa.String(2), server_default="en", nullable=False))
        b.create_foreign_key("fk_users_referred_by", "users", ["referred_by_id"], ["id"], ondelete="SET NULL")
        b.create_index("ix_users_referral_code", ["referral_code"], unique=True)
    with op.batch_alter_table("orders") as b:
        b.add_column(sa.Column("gift_message", sa.String(500), nullable=True))
        b.add_column(sa.Column("hide_prices", sa.Boolean(), server_default=sa.false(), nullable=False))
    with op.batch_alter_table("products") as b:
        b.add_column(sa.Column("name_ta", sa.String(200), nullable=True))
        b.add_column(sa.Column("description_ta", sa.Text(), nullable=True))
    with op.batch_alter_table("categories") as b:
        b.add_column(sa.Column("name_ta", sa.String(120), nullable=True))
        b.add_column(sa.Column("description_ta", sa.Text(), nullable=True))
    with op.batch_alter_table("recipe_videos") as b:
        b.add_column(sa.Column("name_ta", sa.String(180), nullable=True))
        b.add_column(sa.Column("description_ta", sa.Text(), nullable=True))
    op.create_table("points_ledger", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL")), sa.Column("points", sa.Integer(), nullable=False), sa.Column("entry_type", sa.String(12), nullable=False), sa.Column("reason", sa.String(240), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_points_ledger_user_id", "points_ledger", ["user_id"])
    op.create_index("ix_points_ledger_order_id", "points_ledger", ["order_id"])
    op.create_table("search_terms", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("term", sa.String(120), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_search_terms_term", "search_terms", ["term"]); op.create_index("ix_search_terms_created_at", "search_terms", ["created_at"])
    op.create_table("recipe_favourites", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("recipe_id", sa.Integer(), sa.ForeignKey("recipe_videos.id", ondelete="CASCADE"), nullable=False), sa.UniqueConstraint("user_id", "recipe_id", name="uq_recipe_favourite"))
    op.create_index("ix_recipe_favourites_user_id", "recipe_favourites", ["user_id"]); op.create_index("ix_recipe_favourites_recipe_id", "recipe_favourites", ["recipe_id"])
def downgrade():
    op.drop_table("recipe_favourites"); op.drop_table("search_terms"); op.drop_table("points_ledger")
    for table, cols in (("recipe_videos", ["name_ta", "description_ta"]),("categories", ["name_ta", "description_ta"]),("products", ["name_ta", "description_ta"]),("orders", ["gift_message", "hide_prices"])):
        with op.batch_alter_table(table) as b:
            for col in cols: b.drop_column(col)
    with op.batch_alter_table("users") as b:
        b.drop_index("ix_users_referral_code"); b.drop_constraint("fk_users_referred_by", type_="foreignkey")
        b.drop_column("preferred_language"); b.drop_column("referred_by_id"); b.drop_column("referral_code")
