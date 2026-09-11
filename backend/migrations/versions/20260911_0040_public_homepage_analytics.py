"""Add anonymous reach analytics for the public masterclass homepage.

Revision ID: 20260911_0040
Revises: 20260908_0039
"""

from __future__ import annotations

from alembic import op


revision = "20260911_0040"
down_revision = "20260908_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public_homepage_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id varchar(36) NOT NULL,
            viewer_key varchar(64) NOT NULL,
            page_id varchar(120) NOT NULL,
            page_path varchar(255) NOT NULL,
            event_type varchar(32) NOT NULL,
            section_id varchar(80) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_public_homepage_events_session_event
                UNIQUE (session_id, page_id, event_type, section_id)
        );
        CREATE INDEX ix_public_homepage_events_page_section_created
            ON public_homepage_events(page_id, section_id, created_at);
        CREATE INDEX ix_public_homepage_events_viewer
            ON public_homepage_events(viewer_key);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public_homepage_events")
