"""Persist the learner timezone for the calorie course's 06:00 unlock."""

from alembic import op
import sqlalchemy as sa

revision = "20260925_0048"
down_revision = "20260921_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course_stage_progress",
        sa.Column("timezone_name", sa.String(64), server_default="Europe/Moscow", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("course_stage_progress", "timezone_name")
