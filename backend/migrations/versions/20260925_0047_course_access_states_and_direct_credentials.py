"""Add course start states and direct credential email delivery.

Revision ID: 20260925_0047
Revises: 20260921_0047
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260925_0047"
down_revision = "20260921_0047"
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
        "personal_access_links",
        sa.Column("target_email_original", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "personal_access_links",
        sa.Column("target_email_normalized", sa.String(length=320), nullable=True),
    )
    # Historical links normally have a primary email.  The fallback to the
    # oldest attached email makes the migration safe for legacy rows imported
    # before the primary flag existed.
    op.execute(
        """
        UPDATE personal_access_links AS link
        SET target_email_original = email.email_original,
            target_email_normalized = email.email_normalized
        FROM (
            SELECT DISTINCT ON (user_id)
                user_id, email_original, email_normalized
            FROM user_emails
            ORDER BY user_id, is_primary DESC, created_at ASC
        ) AS email
        WHERE email.user_id = link.user_id
        """
    )
    op.alter_column("personal_access_links", "target_email_original", nullable=False)
    op.alter_column("personal_access_links", "target_email_normalized", nullable=False)
    op.create_index(
        "ix_personal_access_links_target_email_normalized",
        "personal_access_links",
        ["target_email_normalized"],
    )
    op.alter_column("personal_access_links", "user_id", nullable=True)
    op.add_column(
        "user_course_policies",
        sa.Column("start_mode", sa.String(length=32), nullable=False, server_default="auto"),
    )
    op.create_check_constraint(
        "ck_user_course_start_mode",
        "user_course_policies",
        "start_mode IN ('auto','open','blocked')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_user_course_start_mode", "user_course_policies", type_="check")
    op.drop_column("user_course_policies", "start_mode")
    op.alter_column("personal_access_links", "user_id", nullable=False)
    op.drop_index("ix_personal_access_links_target_email_normalized", table_name="personal_access_links")
    op.drop_column("personal_access_links", "target_email_normalized")
    op.drop_column("personal_access_links", "target_email_original")
    op.drop_column("personal_access_links", "start_modes")
    op.drop_column("account_onboardings", "delivery_mode")
