"""Add one-row-per-user application state tables.

Revision ID: 20260822_0004
Revises: 20260822_0003
"""

from alembic import op


revision = "20260822_0004"
down_revision = "20260822_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE dqs_states (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            start_date varchar(10),
            days jsonb NOT NULL DEFAULT '{}'::jsonb,
            version integer NOT NULL DEFAULT 1,
            source varchar(64) NOT NULL DEFAULT 'app',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_dqs_states_user_id ON dqs_states(user_id);

        CREATE TABLE strength_states (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            workout_types jsonb NOT NULL DEFAULT '[]'::jsonb,
            hidden_exercises jsonb NOT NULL DEFAULT '[]'::jsonb,
            workouts jsonb NOT NULL DEFAULT '[]'::jsonb,
            version integer NOT NULL DEFAULT 1,
            source varchar(64) NOT NULL DEFAULT 'app',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_strength_states_user_id ON strength_states(user_id);

        CREATE TABLE strength_exercises (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(128) NOT NULL UNIQUE,
            name varchar(255) NOT NULL,
            active boolean NOT NULL DEFAULT true,
            sort_order integer NOT NULL DEFAULT 0,
            metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE metabolism_states (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            variants jsonb NOT NULL DEFAULT '{}'::jsonb,
            active_variant integer NOT NULL DEFAULT 1,
            formula_version varchar(32) NOT NULL DEFAULT 'metabolism_v3',
            version integer NOT NULL DEFAULT 1,
            source varchar(64) NOT NULL DEFAULT 'app',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_metabolism_active_variant CHECK (active_variant IN (1, 2))
        );
        CREATE INDEX ix_metabolism_states_user_id ON metabolism_states(user_id);

        CREATE TABLE admin_app_edits (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            admin_username varchar(255) NOT NULL,
            target_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            app_code varchar(32) NOT NULL,
            action varchar(64) NOT NULL,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_admin_app_edits_target_user_id ON admin_app_edits(target_user_id);

        INSERT INTO resources (code, name, status)
        VALUES
            ('dqs', 'Diet Quality Score', 'active'),
            ('strength', 'Силовые тренировки', 'active'),
            ('metabolism', 'Калькулятор метаболизма', 'active')
        ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, status = 'active';
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS admin_app_edits;
        DROP TABLE IF EXISTS metabolism_states;
        DROP TABLE IF EXISTS strength_exercises;
        DROP TABLE IF EXISTS strength_states;
        DROP TABLE IF EXISTS dqs_states;
    """)
