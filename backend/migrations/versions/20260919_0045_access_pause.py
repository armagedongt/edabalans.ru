"""Add manual pause to product access.

Revision ID: 20260919_0045
Revises: 20260919_0044
"""

from alembic import op
import sqlalchemy as sa


revision = "20260919_0045"
down_revision = "20260919_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_accesses", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("user_accesses", "paused_at")
