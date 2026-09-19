"""Add admin-readable credential copy.

Revision ID: 20260919_0044
Revises: 20260918_0043
"""

from alembic import op
import sqlalchemy as sa


revision = "20260919_0044"
down_revision = "20260918_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("account_credentials", sa.Column("password_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("account_credentials", "password_ciphertext")
