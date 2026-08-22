"""Add short-lived messenger account link tokens.

Revision ID: 20260823_0016
Revises: 20260822_0015
"""

from alembic import op


revision = "20260823_0016"
down_revision = "20260822_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE messenger_link_tokens (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            platform varchar(32) NOT NULL,
            purpose varchar(64) NOT NULL,
            token_hash varchar(64) NOT NULL UNIQUE,
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_messenger_link_tokens_user_id
            ON messenger_link_tokens(user_id);
        CREATE INDEX ix_messenger_link_active
            ON messenger_link_tokens(user_id, platform, purpose, expires_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS messenger_link_tokens;")
