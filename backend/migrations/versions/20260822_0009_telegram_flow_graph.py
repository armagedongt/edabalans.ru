"""Make Telegram routes and transitions the executable graph.

Revision ID: 20260822_0009
Revises: 20260822_0008
"""

from alembic import op


revision = "20260822_0009"
down_revision = "20260822_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tg_sequence_edges (
            id varchar(36) PRIMARY KEY,
            sequence_version_id varchar(36) NOT NULL REFERENCES tg_sequence_versions(id),
            from_step_key varchar(120) NOT NULL,
            to_step_key varchar(120),
            target_sequence_code varchar(100),
            branch_key varchar(40) NOT NULL DEFAULT 'default',
            label varchar(255),
            condition json NOT NULL DEFAULT '{}',
            priority integer NOT NULL DEFAULT 0,
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_tg_sequence_edge_branch UNIQUE(sequence_version_id, from_step_key, branch_key, priority),
            CONSTRAINT ck_tg_sequence_edge_target CHECK (to_step_key IS NOT NULL OR target_sequence_code IS NOT NULL)
        );
        CREATE INDEX ix_tg_sequence_edges_sequence_version_id ON tg_sequence_edges(sequence_version_id);

        CREATE TABLE tg_bot_routes (
            id varchar(36) PRIMARY KEY,
            code varchar(100) UNIQUE NOT NULL,
            name varchar(255) NOT NULL,
            trigger_kind varchar(64) NOT NULL,
            trigger_value varchar(255) NOT NULL,
            source_component varchar(120) NOT NULL,
            target_sequence_code varchar(100) NOT NULL,
            configuration json NOT NULL DEFAULT '{}',
            priority integer NOT NULL DEFAULT 0,
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_tg_bot_routes_trigger_kind ON tg_bot_routes(trigger_kind);

        INSERT INTO tg_sequence_edges (
            id, sequence_version_id, from_step_key, to_step_key,
            branch_key, label, condition, priority, enabled
        )
        SELECT
            md5(random()::text || clock_timestamp()::text || step.id),
            step.sequence_version_id,
            step.step_key,
            COALESCE(
                CASE WHEN step.kind = 'GOTO' THEN step.configuration->>'step_key' END,
                step.next_step_key,
                following.step_key
            ),
            'default', 'Далее', '{}', 0, true
        FROM tg_sequence_steps step
        LEFT JOIN LATERAL (
            SELECT candidate.step_key
            FROM tg_sequence_steps candidate
            WHERE candidate.sequence_version_id = step.sequence_version_id
              AND candidate.enabled = true
              AND candidate.position > step.position
            ORDER BY candidate.position
            LIMIT 1
        ) following ON true
        WHERE step.enabled = true
          AND step.kind NOT IN ('STOP', 'CONDITION')
          AND COALESCE(
              CASE WHEN step.kind = 'GOTO' THEN step.configuration->>'step_key' END,
              step.next_step_key,
              following.step_key
          ) IS NOT NULL;

        INSERT INTO tg_sequence_edges (
            id, sequence_version_id, from_step_key, to_step_key,
            target_sequence_code, branch_key, label, condition, priority, enabled
        )
        SELECT
            md5(random()::text || clock_timestamp()::text || step.id || 'true'),
            step.sequence_version_id,
            step.step_key,
            COALESCE(
                step.configuration->>'true_step',
                CASE WHEN step.configuration->>'true_sequence' IS NULL THEN following.step_key END
            ),
            step.configuration->>'true_sequence',
            'true', 'Да', '{}', 0, true
        FROM tg_sequence_steps step
        LEFT JOIN LATERAL (
            SELECT candidate.step_key
            FROM tg_sequence_steps candidate
            WHERE candidate.sequence_version_id = step.sequence_version_id
              AND candidate.enabled = true
              AND candidate.position > step.position
            ORDER BY candidate.position
            LIMIT 1
        ) following ON true
        WHERE step.enabled = true AND step.kind = 'CONDITION'
          AND (step.configuration->>'true_step' IS NOT NULL
               OR step.configuration->>'true_sequence' IS NOT NULL
               OR following.step_key IS NOT NULL);

        INSERT INTO tg_sequence_edges (
            id, sequence_version_id, from_step_key, to_step_key,
            branch_key, label, condition, priority, enabled
        )
        SELECT
            md5(random()::text || clock_timestamp()::text || step.id || 'false'),
            step.sequence_version_id,
            step.step_key,
            COALESCE(step.configuration->>'false_step', following.step_key),
            'false', 'Нет', '{}', 0, true
        FROM tg_sequence_steps step
        LEFT JOIN LATERAL (
            SELECT candidate.step_key
            FROM tg_sequence_steps candidate
            WHERE candidate.sequence_version_id = step.sequence_version_id
              AND candidate.enabled = true
              AND candidate.position > step.position
            ORDER BY candidate.position
            LIMIT 1
        ) following ON true
        WHERE step.enabled = true AND step.kind = 'CONDITION'
          AND COALESCE(step.configuration->>'false_step', following.step_key) IS NOT NULL;

        INSERT INTO tg_bot_routes (
            id, code, name, trigger_kind, trigger_value, source_component,
            target_sequence_code, configuration, priority, enabled
        ) VALUES (
            md5(random()::text || clock_timestamp()::text),
            'main_start', 'Главный вход в бота', 'telegram_command', '/start',
            'telegram.start', 'prepurchase_masterclass',
            '{"pipeline":["crm.identity.resolve","attribution.resolve"]}', 10, true
        );
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS tg_bot_routes;
        DROP TABLE IF EXISTS tg_sequence_edges;
    """)
