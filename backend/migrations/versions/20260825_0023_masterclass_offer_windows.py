"""Align masterclass offer windows with the approved 72-hour early stage.

Revision ID: 20260825_0023
Revises: 20260824_0022

Existing user_offers keep their stored started_at and expires_at.  Only future
windows read the corrected duration from offer_stages.
"""

from alembic import op


revision = "20260825_0023"
down_revision = "20260824_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE offer_stages SET duration_hours = 72 "
        "WHERE code = 'early' AND duration_hours = 96"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE offer_stages SET duration_hours = 96 "
        "WHERE code = 'early' AND duration_hours = 72"
    )
