"""Normalize legacy CRM facts and add reversible review state.

Revision ID: 20260822_0007
Revises: 20260822_0006
"""

from alembic import op

revision = "20260822_0007"
down_revision = "20260822_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE payments ALTER COLUMN amount DROP NOT NULL;
        ALTER TABLE payments ADD COLUMN review_status varchar(32) NOT NULL DEFAULT 'not_required';
        ALTER TABLE users ADD COLUMN access_review_status varchar(32) NOT NULL DEFAULT 'not_required';
        ALTER TABLE users ADD COLUMN access_review_note text;
        ALTER TABLE users ADD COLUMN access_reviewed_at timestamptz;
        ALTER TABLE users ADD COLUMN tilda_access_status varchar(32) NOT NULL DEFAULT 'not_checked';
        ALTER TABLE messenger_accounts ADD COLUMN subscription_status varchar(32) NOT NULL DEFAULT 'unknown';
        ALTER TABLE messenger_accounts ADD COLUMN subscription_checked_at timestamptz;
        ALTER TABLE messenger_accounts ADD COLUMN main_scenario_seen_at timestamptz;
        ALTER TABLE tags DROP CONSTRAINT IF EXISTS ck_tags_status;
        ALTER TABLE tags ADD CONSTRAINT ck_tags_status CHECK (status IN ('active','archived','review','merged'));
        ALTER TABLE tags ADD COLUMN audit_action varchar(64);
        ALTER TABLE tags ADD COLUMN audit_reason text;
        ALTER TABLE tags ADD COLUMN archived_at timestamptz;
        CREATE INDEX ix_users_access_review_status ON users(access_review_status);
        CREATE INDEX ix_payments_review_status ON payments(review_status);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_payments_review_status;
        DROP INDEX IF EXISTS ix_users_access_review_status;
        ALTER TABLE tags DROP COLUMN IF EXISTS archived_at;
        ALTER TABLE tags DROP COLUMN IF EXISTS audit_reason;
        ALTER TABLE tags DROP COLUMN IF EXISTS audit_action;
        ALTER TABLE tags DROP CONSTRAINT IF EXISTS ck_tags_status;
        UPDATE tags SET status='ignored' WHERE status IN ('archived','review');
        ALTER TABLE tags ADD CONSTRAINT ck_tags_status CHECK (status IN ('active','ignored','merged'));
        ALTER TABLE messenger_accounts DROP COLUMN IF EXISTS main_scenario_seen_at;
        ALTER TABLE messenger_accounts DROP COLUMN IF EXISTS subscription_checked_at;
        ALTER TABLE messenger_accounts DROP COLUMN IF EXISTS subscription_status;
        ALTER TABLE users DROP COLUMN IF EXISTS tilda_access_status;
        ALTER TABLE users DROP COLUMN IF EXISTS access_reviewed_at;
        ALTER TABLE users DROP COLUMN IF EXISTS access_review_note;
        ALTER TABLE users DROP COLUMN IF EXISTS access_review_status;
        ALTER TABLE payments DROP COLUMN IF EXISTS review_status;
        UPDATE payments SET amount = 0 WHERE amount IS NULL;
        ALTER TABLE payments ALTER COLUMN amount SET NOT NULL;
    """)
