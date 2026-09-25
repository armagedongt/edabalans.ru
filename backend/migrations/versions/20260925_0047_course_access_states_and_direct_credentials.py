"""Add course start states and direct credential email delivery.

Revision ID: 20260925_0047
Revises: 20260920_0046
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260925_0047"
down_revision = "20260920_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_onboardings",
        sa.Column("delivery_mode", sa.String(length=32), nullable=False, server_default="messenger_claim"),
    )
    op.add_column(
        "personal_access_links",
        sa.Column("start_modes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "user_course_policies",
        sa.Column("start_mode", sa.String(length=32), nullable=False, server_default="open"),
    )
    op.create_check_constraint(
        "ck_user_course_start_mode",
        "user_course_policies",
        "start_mode IN ('open','blocked')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_user_course_start_mode", "user_course_policies", type_="check")
    op.drop_column("user_course_policies", "start_mode")
    op.drop_column("personal_access_links", "start_modes")
    op.drop_column("account_onboardings", "delivery_mode")
