"""merge order status and delivered timestamp branches

Revision ID: 0b0d5552b3f8
Revises: c5a2d9e81f47, f4a91d7c2e10
Create Date: 2026-11-03 13:40:50.672076

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0b0d5552b3f8'
down_revision = ('c5a2d9e81f47', 'f4a91d7c2e10')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
