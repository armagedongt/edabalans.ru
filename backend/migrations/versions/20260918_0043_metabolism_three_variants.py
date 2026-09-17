"""Allow the third active metabolism variant without rewriting saved calculations.

Revision ID: 20260918_0043
Revises: 20260917_0042
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260918_0043"
down_revision = "20260917_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_metabolism_active_variant", "metabolism_states", type_="check")
    op.create_check_constraint("ck_metabolism_active_variant", "metabolism_states", "active_variant IN (1, 2, 3)")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM metabolism_states WHERE active_variant = 3 LIMIT 1")).first():
        raise RuntimeError("Select variant 1 or 2 before downgrading; saved calculations will not be rewritten automatically")
    op.drop_constraint("ck_metabolism_active_variant", "metabolism_states", type_="check")
    op.create_check_constraint("ck_metabolism_active_variant", "metabolism_states", "active_variant IN (1, 2)")
