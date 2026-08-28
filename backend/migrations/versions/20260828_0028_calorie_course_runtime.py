"""Add reusable stage progress for the calorie course.

Revision ID: 20260828_0028
Revises: 20260827_0027
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828_0028"
down_revision = "20260827_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "course_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_code", sa.String(length=80), nullable=False),
        sa.Column("event_key", sa.String(length=160), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("placement", sa.String(length=80)),
        sa.Column("details", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "course_code", "event_key", name="uq_course_user_event_key"),
    )
    op.create_index(
        "ix_course_event_user_type",
        "course_events",
        ["user_id", "course_code", "event_type"],
    )
    op.create_index("ix_course_events_user_id", "course_events", ["user_id"])

    op.create_table(
        "course_stage_progress",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_code", sa.String(length=80), nullable=False),
        sa.Column("stage_number", sa.Integer(), nullable=False),
        sa.Column("first_opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("task_opened_at", sa.DateTime(timezone=True)),
        sa.Column("structure_revision_no", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("required_step_ids", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("required_check_ids", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("checkmarks", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "course_code", "stage_number", name="uq_course_stage_progress"),
    )
    op.create_index(
        "ix_course_stage_user_number",
        "course_stage_progress",
        ["user_id", "course_code", "stage_number"],
    )
    op.create_index("ix_course_stage_progress_user_id", "course_stage_progress", ["user_id"])

    op.create_table(
        "course_step_progress",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_code", sa.String(length=80), nullable=False),
        sa.Column("stage_number", sa.Integer(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_kind", sa.String(length=32), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "course_code", "stage_number", "step_index",
            name="uq_course_step_progress",
        ),
    )
    op.create_index(
        "ix_course_step_user_stage",
        "course_step_progress",
        ["user_id", "course_code", "stage_number"],
    )
    op.create_index("ix_course_step_progress_user_id", "course_step_progress", ["user_id"])


def downgrade() -> None:
    op.drop_table("course_step_progress")
    op.drop_table("course_stage_progress")
    op.drop_table("course_events")
