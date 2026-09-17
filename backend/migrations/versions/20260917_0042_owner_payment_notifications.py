"""Add durable owner payment-alert outbox.

Revision ID: 20260917_0042
Revises: 20260912_0041
"""

from __future__ import annotations

from alembic import op


revision = "20260917_0042"
down_revision = "20260912_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE owner_payment_notifications (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            payment_id uuid NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
            event_kind varchar(32) NOT NULL,
            message_text text NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'pending',
            attempt_count integer NOT NULL DEFAULT 0,
            next_attempt_at timestamptz,
            sent_at timestamptz,
            delivery_message_id varchar(128),
            last_error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_owner_payment_notification_event UNIQUE (payment_id, event_kind)
        );
        CREATE INDEX ix_owner_payment_notifications_due
            ON owner_payment_notifications(status, next_attempt_at);
        CREATE INDEX ix_owner_payment_notifications_payment_id
            ON owner_payment_notifications(payment_id);
        CREATE TABLE tg_owner_payment_alert_deliveries (
            notification_id varchar(36) PRIMARY KEY,
            message_digest varchar(64) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'sending',
            attempt_count integer NOT NULL DEFAULT 1,
            platform_message_id varchar(128),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS tg_owner_payment_alert_deliveries;
        DROP TABLE IF EXISTS owner_payment_notifications;
    """)
