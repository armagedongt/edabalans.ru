"""Distinguish actual and reconstructed payment amounts.

Revision ID: 20260822_0011
Revises: 20260822_0010
"""

import sqlalchemy as sa
from alembic import op


revision = "20260822_0011"
down_revision = "20260822_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column(
            "amount_is_estimated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_payments_amount_is_estimated",
        "payments",
        ["amount_is_estimated"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payments_amount_is_estimated", table_name="payments")
    op.drop_column("payments", "amount_is_estimated")
