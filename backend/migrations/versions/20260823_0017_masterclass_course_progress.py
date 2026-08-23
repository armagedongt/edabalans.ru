"""Add persistent progress for the 21-day masterclass course.

Revision ID: 20260823_0017
Revises: 20260823_0016
"""

from alembic import op


revision = "20260823_0017"
down_revision = "20260823_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE masterclass_day_progress (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            day_number integer NOT NULL,
            first_opened_at timestamptz NOT NULL DEFAULT now(),
            task_opened_at timestamptz,
            checkmarks json NOT NULL DEFAULT '{}',
            completed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_masterclass_day_progress UNIQUE(user_id, day_number),
            CONSTRAINT ck_masterclass_day_number CHECK(day_number BETWEEN 1 AND 21)
        );
        CREATE INDEX ix_masterclass_day_progress_user_id
            ON masterclass_day_progress(user_id);
        CREATE INDEX ix_masterclass_day_user_number
            ON masterclass_day_progress(user_id, day_number);

        CREATE TABLE masterclass_step_progress (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            day_number integer NOT NULL,
            step_index integer NOT NULL,
            step_kind varchar(32) NOT NULL,
            completed_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_masterclass_step_progress
                UNIQUE(user_id, day_number, step_index),
            CONSTRAINT ck_masterclass_step_day CHECK(day_number BETWEEN 1 AND 21),
            CONSTRAINT ck_masterclass_step_index CHECK(step_index >= 0)
        );
        CREATE INDEX ix_masterclass_step_progress_user_id
            ON masterclass_step_progress(user_id);
        CREATE INDEX ix_masterclass_step_user_day
            ON masterclass_step_progress(user_id, day_number);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS masterclass_step_progress;
        DROP TABLE IF EXISTS masterclass_day_progress;
    """)
