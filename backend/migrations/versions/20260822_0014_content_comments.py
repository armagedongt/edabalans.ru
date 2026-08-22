"""Add imported content comments.

Revision ID: 20260822_0014
Revises: 20260822_0013
"""

from alembic import op


revision = "20260822_0014"
down_revision = "20260822_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE content_comments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            external_id varchar(128) NOT NULL,
            parent_external_id varchar(128),
            depth integer NOT NULL DEFAULT 0,
            author_name varchar(255),
            author_external_id varchar(255),
            is_owner_comment boolean NOT NULL DEFAULT false,
            published_at timestamptz,
            text_content text NOT NULL,
            permalink text,
            rating integer,
            pluses integer,
            minuses integer,
            emotions json NOT NULL DEFAULT '[]',
            metadata_json json NOT NULL DEFAULT '{}',
            imported_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_content_comment_external UNIQUE(item_id, external_id)
        );
        CREATE INDEX ix_content_comments_item_id ON content_comments(item_id);
        CREATE INDEX ix_content_comment_item_parent
            ON content_comments(item_id, parent_external_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS content_comments;")
