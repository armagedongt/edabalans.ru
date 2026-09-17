"""Add the cross-messenger practice-chat bridge tables.

Revision ID: 20260917_0042
Revises: 20260912_0041
Create Date: 2026-09-17
"""

from alembic import op


revision = "20260917_0042"
down_revision = "20260912_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE messaging_bridge_pairs (
            id varchar(36) PRIMARY KEY,
            key varchar(120) UNIQUE NOT NULL,
            status varchar(16) NOT NULL DEFAULT 'draft',
            telegram_channel_id varchar(64) NOT NULL,
            max_channel_id varchar(128) NOT NULL,
            telegram_practice_chat_id varchar(64) NOT NULL,
            max_practice_chat_id varchar(128) NOT NULL,
            sync_edits boolean NOT NULL DEFAULT true,
            sync_deletions boolean NOT NULL DEFAULT true,
            started_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE messaging_bridge_messages (
            id varchar(36) PRIMARY KEY,
            pair_id varchar(36) NOT NULL REFERENCES messaging_bridge_pairs(id) ON DELETE CASCADE,
            kind varchar(16) NOT NULL,
            telegram_message_id varchar(128),
            max_message_id varchar(128),
            source_platform varchar(16) NOT NULL,
            source_author_name varchar(255),
            parent_message_id varchar(36) REFERENCES messaging_bridge_messages(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_bridge_pair_telegram_message UNIQUE(pair_id, telegram_message_id),
            CONSTRAINT uq_bridge_pair_max_message UNIQUE(pair_id, max_message_id)
        );
        CREATE INDEX ix_messaging_bridge_messages_pair_id ON messaging_bridge_messages(pair_id);
        CREATE INDEX ix_messaging_bridge_messages_parent_message_id ON messaging_bridge_messages(parent_message_id);
        CREATE TABLE messaging_bridge_receipts (
            id varchar(36) PRIMARY KEY,
            platform varchar(16) NOT NULL,
            event_key varchar(255) NOT NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_bridge_platform_event UNIQUE(platform, event_key)
        );
        CREATE TABLE messaging_bridge_deliveries (
            id varchar(36) PRIMARY KEY,
            message_id varchar(36) NOT NULL REFERENCES messaging_bridge_messages(id) ON DELETE CASCADE,
            target_platform varchar(16) NOT NULL,
            status varchar(16) NOT NULL DEFAULT 'pending',
            attempts integer NOT NULL DEFAULT 0,
            payload json NOT NULL DEFAULT '{}'::json,
            error_message text,
            retry_at timestamptz,
            delivered_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_bridge_delivery_target UNIQUE(message_id, target_platform)
        );
        CREATE INDEX ix_messaging_bridge_deliveries_message_id ON messaging_bridge_deliveries(message_id);
        CREATE INDEX ix_messaging_bridge_deliveries_retry_at ON messaging_bridge_deliveries(retry_at);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS messaging_bridge_deliveries;
        DROP TABLE IF EXISTS messaging_bridge_receipts;
        DROP TABLE IF EXISTS messaging_bridge_messages;
        DROP TABLE IF EXISTS messaging_bridge_pairs;
    """)
