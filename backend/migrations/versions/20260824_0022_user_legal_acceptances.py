"""Store versioned legal acceptances for the universal account.

Revision ID: 20260824_0022
Revises: 20260824_0021
"""

from alembic import op


revision = "20260824_0022"
down_revision = "20260824_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE user_legal_acceptances (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            document_code varchar(64) NOT NULL,
            document_version varchar(64) NOT NULL,
            source varchar(64) NOT NULL,
            accepted_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_legal_acceptance_version
                UNIQUE (user_id, document_code, document_version)
        );
        CREATE INDEX ix_user_legal_acceptances_user
            ON user_legal_acceptances (user_id, accepted_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_legal_acceptances;")
