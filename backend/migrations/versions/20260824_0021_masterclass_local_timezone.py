"""Store the local timezone used by each masterclass day.

Revision ID: 20260824_0021
Revises: 20260823_0020
"""

from alembic import op


revision = "20260824_0021"
down_revision = "20260823_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE masterclass_day_progress
        ADD COLUMN timezone_name varchar(64) NOT NULL DEFAULT 'Europe/Moscow';
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE masterclass_day_progress
        DROP COLUMN IF EXISTS timezone_name;
    """)
