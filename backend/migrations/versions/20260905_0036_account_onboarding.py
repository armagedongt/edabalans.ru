"""Add durable post-paid account onboarding.

Revision ID: 20260905_0036
Revises: 20260905_0035
"""

from alembic import op

revision = "20260905_0036"
down_revision = "20260905_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE account_onboardings (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            payment_id uuid NOT NULL UNIQUE REFERENCES payments(id) ON DELETE CASCADE,
            claim_bundle_encrypted text NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'ready',
            expires_at timestamptz NOT NULL,
            claimed_platform varchar(32),
            claimed_at timestamptz,
            email_status varchar(32) NOT NULL DEFAULT 'pending',
            email_attempt_count integer NOT NULL DEFAULT 0,
            next_email_attempt_at timestamptz,
            email_sent_at timestamptz,
            email_error text,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_account_onboardings_user_id ON account_onboardings(user_id);
        CREATE INDEX ix_account_onboardings_email_due
            ON account_onboardings(email_status, next_email_attempt_at);

        ALTER TABLE messenger_link_tokens
            ADD COLUMN account_onboarding_id uuid
            REFERENCES account_onboardings(id) ON DELETE CASCADE;
        CREATE INDEX ix_messenger_link_tokens_account_onboarding_id
            ON messenger_link_tokens(account_onboarding_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_messenger_link_tokens_account_onboarding_id;
        ALTER TABLE messenger_link_tokens DROP COLUMN IF EXISTS account_onboarding_id;
        DROP TABLE IF EXISTS account_onboardings;
    """)
