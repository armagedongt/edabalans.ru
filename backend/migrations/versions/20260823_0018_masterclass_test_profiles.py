"""Add isolated accelerated masterclass profiles for owner testing.

Revision ID: 20260823_0018
Revises: 20260823_0017
"""

from alembic import op


revision = "20260823_0018"
down_revision = "20260823_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE masterclass_test_profiles (
            user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            enabled boolean NOT NULL DEFAULT true,
            day_interval_seconds integer NOT NULL DEFAULT 20,
            notification_delay_seconds integer NOT NULL DEFAULT 10,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_masterclass_test_day_interval CHECK(day_interval_seconds BETWEEN 1 AND 3600),
            CONSTRAINT ck_masterclass_test_notification_delay CHECK(notification_delay_seconds BETWEEN 1 AND 3600)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS masterclass_test_profiles;")
