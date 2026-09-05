"""Add native account credentials and sessions.

Revision ID: 20260905_0035
Revises: 20260901_0034
"""

from alembic import op

revision = "20260905_0035"
down_revision = "20260901_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE account_credentials (
            user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            password_hash text NOT NULL,
            password_version integer NOT NULL DEFAULT 1,
            issued_via varchar(32) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE account_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash varchar(64) NOT NULL UNIQUE,
            password_version integer NOT NULL,
            expires_at timestamptz NOT NULL,
            revoked_at timestamptz,
            last_seen_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_account_sessions_user_id ON account_sessions(user_id);
        CREATE INDEX ix_account_sessions_active
            ON account_sessions(user_id, expires_at, revoked_at);

    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS account_sessions;
        DROP TABLE IF EXISTS account_credentials;
    """)
