"""Store reproducible daily marketing reports.

Revision ID: 20260908_0038
Revises: 20260906_0037
"""

from alembic import op


revision = "20260908_0038"
down_revision = "20260906_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE marketing_daily_reports (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            report_date varchar(10) NOT NULL UNIQUE,
            period_start timestamptz NOT NULL,
            period_end timestamptz NOT NULL,
            payload_json json NOT NULL DEFAULT '{}',
            telegram_messages json NOT NULL DEFAULT '[]',
            delivery_status varchar(32) NOT NULL DEFAULT 'pending',
            generated_at timestamptz NOT NULL DEFAULT now(),
            sent_at timestamptz,
            delivery_error text
        );
        CREATE INDEX ix_marketing_daily_reports_generated
            ON marketing_daily_reports(generated_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketing_daily_reports")
