"""Add lead entry attribution rules, aliases and exact UTM mappings.

Revision ID: 20260822_0012
Revises: 20260822_0011
"""

from alembic import op


revision = "20260822_0012"
down_revision = "20260822_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE tg_tracking_links ADD COLUMN name varchar(255);
        ALTER TABLE tg_tracking_links ADD COLUMN target_kind varchar(32) NOT NULL DEFAULT 'bot_start';
        ALTER TABLE tg_tracking_links ADD COLUMN route_kind varchar(32) NOT NULL DEFAULT 'root';
        ALTER TABLE tg_tracking_links ADD COLUMN target_step_key varchar(120);
        ALTER TABLE tg_tracking_links ADD COLUMN status varchar(32) NOT NULL DEFAULT 'active';
        ALTER TABLE tg_tracking_links ADD COLUMN created_by varchar(320);
        ALTER TABLE tg_tracking_links ADD COLUMN archived_at timestamptz;
        UPDATE tg_tracking_links SET name = concat(platform, ' · ', placement) WHERE name IS NULL;
        ALTER TABLE tg_tracking_links ALTER COLUMN name SET NOT NULL;

        CREATE TABLE tg_tracking_link_aliases (
            id varchar(36) PRIMARY KEY,
            tracking_link_id varchar(36) NOT NULL REFERENCES tg_tracking_links(id) ON DELETE CASCADE,
            token varchar(64) UNIQUE NOT NULL,
            alias_kind varchar(32) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'active',
            telegram_invite_url text,
            telegram_chat_id varchar(64),
            creates_join_request boolean NOT NULL DEFAULT false,
            created_by varchar(320),
            created_at timestamptz NOT NULL DEFAULT now(),
            archived_at timestamptz
        );
        CREATE INDEX ix_tg_tracking_aliases_link ON tg_tracking_link_aliases(tracking_link_id);
        CREATE INDEX ix_tg_tracking_aliases_status ON tg_tracking_link_aliases(status);
        INSERT INTO tg_tracking_link_aliases (id, tracking_link_id, token, alias_kind, status)
        SELECT gen_random_uuid()::text, id, token,
               CASE WHEN token ~ '^[0-9a-fA-F-]{36}$' THEN 'legacy' ELSE 'short' END,
               CASE WHEN is_active THEN 'active' ELSE 'disabled' END
        FROM tg_tracking_links ON CONFLICT (token) DO NOTHING;

        CREATE TABLE tg_tracking_link_tags (
            tracking_link_id varchar(36) NOT NULL REFERENCES tg_tracking_links(id) ON DELETE CASCADE,
            tag_id uuid NOT NULL REFERENCES tags(id) ON DELETE RESTRICT,
            purpose varchar(32) NOT NULL DEFAULT 'other',
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tracking_link_id, tag_id)
        );
        CREATE INDEX ix_tg_tracking_link_tags_tag ON tg_tracking_link_tags(tag_id);

        CREATE TABLE tg_utm_tag_rules (
            id varchar(36) PRIMARY KEY,
            parameter_name varchar(128) NOT NULL,
            raw_value text NOT NULL,
            normalized_value text NOT NULL,
            tag_id uuid NOT NULL REFERENCES tags(id) ON DELETE RESTRICT,
            status varchar(32) NOT NULL DEFAULT 'active',
            created_by varchar(320),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_tg_utm_rule UNIQUE(parameter_name, normalized_value)
        );
        CREATE INDEX ix_tg_utm_rules_tag ON tg_utm_tag_rules(tag_id);

        CREATE TABLE tg_tracking_sessions (
            id varchar(36) PRIMARY KEY,
            start_token_hash varchar(64) UNIQUE NOT NULL,
            tracking_link_id varchar(36) NOT NULL REFERENCES tg_tracking_links(id) ON DELETE CASCADE,
            alias_id varchar(36) NOT NULL REFERENCES tg_tracking_link_aliases(id) ON DELETE CASCADE,
            raw_query json NOT NULL DEFAULT '{}',
            resolved_tag_ids json NOT NULL DEFAULT '[]',
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz
        );
        CREATE INDEX ix_tg_tracking_sessions_expires ON tg_tracking_sessions(expires_at);

        ALTER TABLE tg_tracking_events ADD COLUMN alias_id varchar(36) REFERENCES tg_tracking_link_aliases(id);
        ALTER TABLE tg_tracking_events ADD COLUMN user_id uuid REFERENCES users(id) ON DELETE SET NULL;
        ALTER TABLE tg_tracking_events ADD COLUMN telegram_user_id varchar(64);
        ALTER TABLE tg_tracking_events ADD COLUMN deduplication_key varchar(255);
        ALTER TABLE tg_tracking_events ADD COLUMN processed_at timestamptz;
        CREATE INDEX ix_tg_tracking_events_alias ON tg_tracking_events(alias_id);
        CREATE INDEX ix_tg_tracking_events_user ON tg_tracking_events(user_id);
        CREATE INDEX ix_tg_tracking_events_telegram_user ON tg_tracking_events(telegram_user_id);
        CREATE UNIQUE INDEX uq_tg_tracking_events_dedup ON tg_tracking_events(deduplication_key)
            WHERE deduplication_key IS NOT NULL;

        UPDATE tg_tracking_events e SET alias_id = a.id
        FROM tg_tracking_link_aliases a
        WHERE a.tracking_link_id = e.tracking_link_id AND e.alias_id IS NULL;
    """)

    for token, platform, placement in (
        ("c5a79797-d6c6-4a36-8551-b07443e990a7", "Пикабу", "Главная ссылка Пикабу"),
        ("120385af-6025-49f9-b586-d01f4ca4d36b", "Не определена", "Пост - Не с похудения"),
        ("b1514e43-2459-456f-949b-5cc25e87bb10", "Не определена", "Пост - Скорость похудения"),
    ):
        op.execute(f"""
            INSERT INTO tg_tracking_links
                (id, token, platform, placement, campaign, target_sequence_code,
                 is_active, name, target_kind, route_kind, status)
            SELECT gen_random_uuid()::text, '{token}', '{platform}', '{placement}', NULL,
                   'prepurchase_masterclass', true, '{placement}', 'bot_start', 'root', 'active'
            WHERE NOT EXISTS (SELECT 1 FROM tg_tracking_links WHERE token = '{token}');
            INSERT INTO tg_tracking_link_aliases
                (id, tracking_link_id, token, alias_kind, status)
            SELECT gen_random_uuid()::text, id, token, 'legacy', 'active'
            FROM tg_tracking_links WHERE token = '{token}'
            ON CONFLICT (token) DO NOTHING;
        """)

    op.execute("""
        INSERT INTO tg_tracking_link_tags (tracking_link_id, tag_id, purpose)
        SELECT l.id, t.id, 'source'
        FROM tg_tracking_links l JOIN tags t ON t.name = 'Пикабу' AND t.status = 'active'
        WHERE l.token = 'c5a79797-d6c6-4a36-8551-b07443e990a7'
        ON CONFLICT DO NOTHING;
        INSERT INTO tg_tracking_link_tags (tracking_link_id, tag_id, purpose)
        SELECT l.id, t.id, 'placement'
        FROM tg_tracking_links l JOIN tags t ON t.name = 'Пост - Не с похудения' AND t.status = 'active'
        WHERE l.token = '120385af-6025-49f9-b586-d01f4ca4d36b'
        ON CONFLICT DO NOTHING;
        INSERT INTO tg_tracking_link_tags (tracking_link_id, tag_id, purpose)
        SELECT l.id, t.id, 'placement'
        FROM tg_tracking_links l JOIN tags t ON t.name = 'Пост - Скорость похудения' AND t.status = 'active'
        WHERE l.token = 'b1514e43-2459-456f-949b-5cc25e87bb10'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS uq_tg_tracking_events_dedup;
        DROP INDEX IF EXISTS ix_tg_tracking_events_telegram_user;
        DROP INDEX IF EXISTS ix_tg_tracking_events_user;
        DROP INDEX IF EXISTS ix_tg_tracking_events_alias;
        ALTER TABLE tg_tracking_events DROP COLUMN IF EXISTS processed_at;
        ALTER TABLE tg_tracking_events DROP COLUMN IF EXISTS deduplication_key;
        ALTER TABLE tg_tracking_events DROP COLUMN IF EXISTS telegram_user_id;
        ALTER TABLE tg_tracking_events DROP COLUMN IF EXISTS user_id;
        ALTER TABLE tg_tracking_events DROP COLUMN IF EXISTS alias_id;
        DROP TABLE IF EXISTS tg_tracking_sessions;
        DROP TABLE IF EXISTS tg_utm_tag_rules;
        DROP TABLE IF EXISTS tg_tracking_link_tags;
        DROP TABLE IF EXISTS tg_tracking_link_aliases;
        ALTER TABLE tg_tracking_links DROP COLUMN IF EXISTS archived_at;
        ALTER TABLE tg_tracking_links DROP COLUMN IF EXISTS created_by;
        ALTER TABLE tg_tracking_links DROP COLUMN IF EXISTS status;
        ALTER TABLE tg_tracking_links DROP COLUMN IF EXISTS target_step_key;
        ALTER TABLE tg_tracking_links DROP COLUMN IF EXISTS route_kind;
        ALTER TABLE tg_tracking_links DROP COLUMN IF EXISTS target_kind;
        ALTER TABLE tg_tracking_links DROP COLUMN IF EXISTS name;
    """)
