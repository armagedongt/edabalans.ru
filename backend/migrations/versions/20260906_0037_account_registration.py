"""Allow account onboarding without a payment for voluntary registration.

Revision ID: 20260906_0037
Revises: 20260905_0036
"""

from alembic import op


revision = "20260906_0037"
down_revision = "20260905_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE account_onboardings ALTER COLUMN payment_id DROP NOT NULL;")


def downgrade() -> None:
    # A downgrade cannot preserve registration rows: the previous schema required
    # every onboarding to reference a payment.
    op.execute("DELETE FROM account_onboardings WHERE payment_id IS NULL;")
    op.execute("ALTER TABLE account_onboardings ALTER COLUMN payment_id SET NOT NULL;")
