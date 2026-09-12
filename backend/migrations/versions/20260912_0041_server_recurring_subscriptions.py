"""Add server-owned recurring subscriptions and their PostgreSQL price.

Revision ID: 20260912_0041
Revises: 20260911_0040
"""

from __future__ import annotations

from alembic import op


revision = "20260912_0041"
down_revision = "20260911_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE recurring_subscriptions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            product_code varchar(80) NOT NULL,
            price_entry_code varchar(120) NOT NULL,
            pricing_version_id uuid REFERENCES pricing_versions(id) ON DELETE SET NULL,
            email_normalized varchar(320) NOT NULL,
            amount numeric(14,2) NOT NULL,
            currency varchar(3) NOT NULL DEFAULT 'RUB',
            status varchar(32) NOT NULL DEFAULT 'pending',
            parent_invoice_id varchar(255) UNIQUE,
            pending_invoice_id varchar(255) UNIQUE,
            successful_payments integer NOT NULL DEFAULT 0,
            current_period_start timestamptz,
            current_period_end timestamptz,
            next_charge_at timestamptz,
            charge_started_at timestamptz,
            next_status_check_at timestamptz,
            status_check_attempts integer NOT NULL DEFAULT 0,
            cancelled_at timestamptz,
            cancellation_source varchar(64),
            last_error text,
            failure_notification_status varchar(32),
            failure_notification_attempts integer NOT NULL DEFAULT 0,
            next_notification_attempt_at timestamptz,
            failure_notified_at timestamptz,
            terms_accepted_at timestamptz NOT NULL,
            terms_ip varchar(64),
            terms_user_agent varchar(500),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_recurring_subscriptions_user_status
            ON recurring_subscriptions(user_id, status);
        CREATE INDEX ix_recurring_subscriptions_due
            ON recurring_subscriptions(status, next_charge_at);
        CREATE INDEX ix_recurring_subscriptions_email
            ON recurring_subscriptions(email_normalized);
        CREATE INDEX ix_recurring_subscriptions_pricing_version_id
            ON recurring_subscriptions(pricing_version_id);

        INSERT INTO price_entries (
            version_id, code, section, name, product_code, resource_codes,
            regular_amount, compare_at_amount, sale_amount, currency,
            enabled, sort_order, metadata_json
        )
        SELECT
            version.id,
            'subscription.coaching.monthly',
            'subscriptions',
            'Индивидуальное сопровождение — 1 месяц',
            'COACHING',
            '[]'::jsonb,
            9800,
            9800,
            9800,
            'RUB',
            true,
            10,
            '{"period":"month","billing":"server_recurring","price_change_requires_new_consent":true}'::jsonb
        FROM pricing_versions version
        WHERE version.status IN ('active', 'draft')
          AND NOT EXISTS (
            SELECT 1 FROM price_entries entry
            WHERE entry.version_id = version.id
              AND entry.code = 'subscription.coaching.monthly'
          );
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM price_entries WHERE code = 'subscription.coaching.monthly';
        DROP TABLE IF EXISTS recurring_subscriptions;
    """)
