"""Persist manual immediate-start overrides for standalone applications.

Revision ID: 20260926_0049
Revises: 20260925_0048
"""

from alembic import op
import sqlalchemy as sa


revision = "20260926_0049"
down_revision = "20260925_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_application_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("app_code", sa.String(length=80), nullable=False),
        sa.Column("start_mode", sa.String(length=32), nullable=False, server_default="auto"),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("start_mode IN ('auto', 'open')", name="ck_user_application_start_mode"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "app_code", name="uq_user_application_policy"),
    )
    op.create_index("ix_user_application_policies_user_id", "user_application_policies", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_application_policies_user_id", table_name="user_application_policies")
    op.drop_table("user_application_policies")
