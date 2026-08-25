"""Add approved temporary site-short offer add-ons.

Revision ID: 20260825_0025
Revises: 20260825_0024
Create Date: 2026-08-25
"""

from alembic import op


revision = "20260825_0025"
down_revision = "20260825_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stage_code, consultation_addon in {
        "early": 7000,
        "second": 7000,
        "review": 7200,
        "last_week": 7900,
    }.items():
        op.execute(
            "UPDATE offer_stages "
            "SET pricing = jsonb_set("
            "COALESCE(pricing::jsonb, '{}'::jsonb), "
            "'{site_short}', "
            f"'{{\"consultation_addon\": {consultation_addon}}}'::jsonb, true"
            ")::json "
            f"WHERE code = '{stage_code}'"
        )


def downgrade() -> None:
    op.execute("UPDATE offer_stages SET pricing = (pricing::jsonb - 'site_short')::json")
