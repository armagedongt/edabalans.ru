"""Store shared editable intensive pages.

Revision ID: 20260824_0023
Revises: 20260824_0022
"""

from alembic import op


revision = "20260824_0023"
down_revision = "20260824_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE intensive_pages (
            day_code varchar(16) PRIMARY KEY,
            body_html text NOT NULL,
            version integer NOT NULL DEFAULT 1,
            updated_by varchar(255) NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_intensive_pages_day_code
                CHECK (day_code IN ('day-1', 'day-2', 'day-3', 'day-4'))
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS intensive_pages;")
