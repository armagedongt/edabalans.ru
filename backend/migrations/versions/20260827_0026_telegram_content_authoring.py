"""Add Telegram content authoring metadata.

Revision ID: 20260827_0026
Revises: 20260825_0025
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_0026"
down_revision = "20260825_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tg_content_items", sa.Column("purpose", sa.Text(), nullable=False, server_default=""))
    op.add_column("tg_content_items", sa.Column("writer_brief", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "tg_content_items",
        sa.Column("editorial_status", sa.String(length=32), nullable=False, server_default="needs_writing"),
    )
    op.add_column(
        "tg_content_items",
        sa.Column("content_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("tg_content_items", "content_version")
    op.drop_column("tg_content_items", "editorial_status")
    op.drop_column("tg_content_items", "writer_brief")
    op.drop_column("tg_content_items", "purpose")
