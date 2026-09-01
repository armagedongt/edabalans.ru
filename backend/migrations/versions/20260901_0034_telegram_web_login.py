"""Add short-lived Telegram web login attempts.

Revision ID: 20260901_0034
Revises: 20260831_0033
"""

from alembic import op

revision = "20260901_0034"
down_revision = "20260831_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE telegram_login_attempts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            nonce_hash varchar(64) NOT NULL UNIQUE,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            telegram_user_id varchar(128) NOT NULL,
            username varchar(255),
            first_name varchar(255),
            verification_code_hash varchar(64) NOT NULL,
            failed_attempts integer NOT NULL DEFAULT 0,
            verified_at timestamptz,
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_telegram_login_attempts_user_id ON telegram_login_attempts(user_id);
        CREATE INDEX ix_telegram_login_attempts_expires_at ON telegram_login_attempts(expires_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS telegram_login_attempts;")
