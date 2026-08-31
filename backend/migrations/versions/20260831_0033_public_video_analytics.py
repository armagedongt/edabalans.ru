"""Add anonymous public video session analytics.

Revision ID: 20260831_0033
Revises: 20260831_0032
"""

from __future__ import annotations

from alembic import op


revision = "20260831_0033"
down_revision = "20260831_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public_video_views (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id varchar(36) NOT NULL UNIQUE,
            viewer_key varchar(64) NOT NULL,
            video_id varchar(120) NOT NULL,
            page_path varchar(255) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'engaged',
            last_event_type varchar(32) NOT NULL,
            last_position_sec integer NOT NULL DEFAULT 0,
            max_position_sec integer NOT NULL DEFAULT 0,
            watched_buckets json NOT NULL DEFAULT '[]',
            event_count integer NOT NULL DEFAULT 0,
            completed boolean NOT NULL DEFAULT false,
            engaged_at timestamptz NOT NULL,
            last_event_at timestamptz NOT NULL,
            completed_at timestamptz,
            exited_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_public_video_views_video_created
            ON public_video_views(video_id, created_at);
        CREATE INDEX ix_public_video_views_viewer
            ON public_video_views(viewer_key);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public_video_views")
