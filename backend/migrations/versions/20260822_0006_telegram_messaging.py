"""Add isolated Telegram messaging engine tables.

Revision ID: 20260822_0006
Revises: 20260822_0005
"""

from alembic import op


revision = "20260822_0006"
down_revision = "20260822_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tg_bot_instances (
            id varchar(36) PRIMARY KEY, code varchar(80) UNIQUE NOT NULL,
            username varchar(255) NOT NULL, display_name varchar(255) NOT NULL,
            token_env_name varchar(128) NOT NULL, is_production boolean NOT NULL,
            is_active boolean NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE tg_content_items (
            id varchar(36) PRIMARY KEY, code varchar(120) UNIQUE NOT NULL,
            title varchar(255) NOT NULL, body_source text NOT NULL,
            source_format varchar(32) NOT NULL, media_kind varchar(32), media_path text,
            telegram_file_id text, labels json NOT NULL, status varchar(32) NOT NULL,
            origin_system varchar(64), origin_scenario_id varchar(64),
            origin_scenario_name varchar(255), origin_block_id varchar(64),
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE tg_sequences (
            id varchar(36) PRIMARY KEY, code varchar(100) UNIQUE NOT NULL,
            name varchar(255) NOT NULL, description text, status varchar(32) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE tg_tracking_links (
            id varchar(36) PRIMARY KEY, token varchar(64) UNIQUE NOT NULL,
            platform varchar(80) NOT NULL, placement varchar(255) NOT NULL,
            campaign varchar(255), target_sequence_code varchar(100) NOT NULL,
            is_active boolean NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE tg_contacts (
            id varchar(36) PRIMARY KEY, bot_instance_id varchar(36) NOT NULL REFERENCES tg_bot_instances(id),
            user_id uuid REFERENCES users(id) ON DELETE SET NULL, telegram_user_id varchar(64) NOT NULL,
            chat_id varchar(64) NOT NULL, username varchar(255), first_name varchar(255),
            last_name varchar(255), language_code varchar(16), status varchar(32) NOT NULL,
            first_source_token varchar(64), last_source_token varchar(64), last_seen_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_tg_contact_bot_user UNIQUE(bot_instance_id, telegram_user_id)
        );
        CREATE INDEX ix_tg_contacts_bot_instance_id ON tg_contacts(bot_instance_id);
        CREATE INDEX ix_tg_contacts_user_id ON tg_contacts(user_id);
        CREATE TABLE tg_sequence_versions (
            id varchar(36) PRIMARY KEY, sequence_id varchar(36) NOT NULL REFERENCES tg_sequences(id),
            version_no integer NOT NULL, status varchar(32) NOT NULL, published_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_tg_sequence_version UNIQUE(sequence_id, version_no)
        );
        CREATE INDEX ix_tg_sequence_versions_sequence_id ON tg_sequence_versions(sequence_id);
        CREATE TABLE tg_update_receipts (
            update_id varchar(64) PRIMARY KEY, bot_instance_id varchar(36) NOT NULL REFERENCES tg_bot_instances(id),
            update_type varchar(32) NOT NULL, received_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE tg_broadcasts (
            id varchar(36) PRIMARY KEY, title varchar(255) NOT NULL,
            content_item_id varchar(36) NOT NULL REFERENCES tg_content_items(id), status varchar(32) NOT NULL,
            segment json NOT NULL, scheduled_at timestamptz, started_at timestamptz, finished_at timestamptz,
            created_by varchar(320), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE tg_sequence_steps (
            id varchar(36) PRIMARY KEY, sequence_version_id varchar(36) NOT NULL REFERENCES tg_sequence_versions(id),
            step_key varchar(120) NOT NULL, position integer NOT NULL, kind varchar(32) NOT NULL,
            label varchar(255) NOT NULL, content_item_id varchar(36) REFERENCES tg_content_items(id),
            delay_seconds integer, next_step_key varchar(120), configuration json NOT NULL, enabled boolean NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_tg_step_key UNIQUE(sequence_version_id, step_key),
            CONSTRAINT uq_tg_step_position UNIQUE(sequence_version_id, position)
        );
        CREATE INDEX ix_tg_sequence_steps_sequence_version_id ON tg_sequence_steps(sequence_version_id);
        CREATE TABLE tg_sequence_runs (
            id varchar(36) PRIMARY KEY, contact_id varchar(36) NOT NULL REFERENCES tg_contacts(id),
            sequence_version_id varchar(36) NOT NULL REFERENCES tg_sequence_versions(id), current_step_key varchar(120),
            status varchar(32) NOT NULL, next_action_at timestamptz, time_scale double precision NOT NULL,
            context json NOT NULL, last_error text, started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_tg_sequence_runs_contact_id ON tg_sequence_runs(contact_id);
        CREATE INDEX ix_tg_sequence_runs_next_action_at ON tg_sequence_runs(next_action_at);
        CREATE INDEX ix_tg_runs_due ON tg_sequence_runs(status, next_action_at);
        CREATE TABLE tg_tracking_events (
            id varchar(36) PRIMARY KEY, tracking_link_id varchar(36) REFERENCES tg_tracking_links(id),
            contact_id varchar(36) REFERENCES tg_contacts(id), event_type varchar(64) NOT NULL,
            metadata_json json NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_tg_tracking_events_tracking_link_id ON tg_tracking_events(tracking_link_id);
        CREATE INDEX ix_tg_tracking_events_contact_id ON tg_tracking_events(contact_id);
        CREATE TABLE tg_user_variables (
            id varchar(36) PRIMARY KEY, contact_id varchar(36) NOT NULL REFERENCES tg_contacts(id),
            key varchar(120) NOT NULL, value json NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_tg_contact_variable UNIQUE(contact_id,key)
        );
        CREATE INDEX ix_tg_user_variables_contact_id ON tg_user_variables(contact_id);
        CREATE TABLE tg_manual_messages (
            id varchar(36) PRIMARY KEY, contact_id varchar(36) NOT NULL REFERENCES tg_contacts(id),
            direction varchar(16) NOT NULL, body_source text NOT NULL, status varchar(32) NOT NULL,
            operator_email varchar(320), platform_message_id varchar(128), created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_tg_manual_messages_contact_id ON tg_manual_messages(contact_id);
        CREATE TABLE tg_broadcast_recipients (
            id varchar(36) PRIMARY KEY, broadcast_id varchar(36) NOT NULL REFERENCES tg_broadcasts(id),
            contact_id varchar(36) NOT NULL REFERENCES tg_contacts(id), status varchar(32) NOT NULL,
            platform_message_id varchar(128), error_message text, sent_at timestamptz,
            CONSTRAINT uq_tg_broadcast_contact UNIQUE(broadcast_id,contact_id)
        );
        CREATE INDEX ix_tg_broadcast_recipients_broadcast_id ON tg_broadcast_recipients(broadcast_id);
        CREATE INDEX ix_tg_broadcast_recipients_contact_id ON tg_broadcast_recipients(contact_id);
        CREATE TABLE tg_step_deliveries (
            id varchar(36) PRIMARY KEY, run_id varchar(36) NOT NULL REFERENCES tg_sequence_runs(id),
            step_key varchar(120) NOT NULL, idempotency_key varchar(255) UNIQUE NOT NULL,
            status varchar(32) NOT NULL, attempt_count integer NOT NULL, platform_message_id varchar(128),
            error_code varchar(80), error_message text, payload_snapshot json NOT NULL,
            scheduled_at timestamptz, sent_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_tg_step_deliveries_run_id ON tg_step_deliveries(run_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS tg_step_deliveries;
        DROP TABLE IF EXISTS tg_broadcast_recipients;
        DROP TABLE IF EXISTS tg_manual_messages;
        DROP TABLE IF EXISTS tg_user_variables;
        DROP TABLE IF EXISTS tg_tracking_events;
        DROP TABLE IF EXISTS tg_sequence_runs;
        DROP TABLE IF EXISTS tg_sequence_steps;
        DROP TABLE IF EXISTS tg_broadcasts;
        DROP TABLE IF EXISTS tg_update_receipts;
        DROP TABLE IF EXISTS tg_sequence_versions;
        DROP TABLE IF EXISTS tg_contacts;
        DROP TABLE IF EXISTS tg_tracking_links;
        DROP TABLE IF EXISTS tg_sequences;
        DROP TABLE IF EXISTS tg_content_items;
        DROP TABLE IF EXISTS tg_bot_instances;
    """)
