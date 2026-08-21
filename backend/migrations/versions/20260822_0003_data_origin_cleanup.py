"""Mark legacy users and expose canonical product names.

Revision ID: 20260822_0003
Revises: 20260822_0002
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_0003"
down_revision = "20260822_0002"
branch_labels = None
depends_on = None


USERS_VIEW = """
CREATE OR REPLACE VIEW crm_users_view AS
SELECT
    u.id AS user_id,
    u.display_name,
    u.status,
    pe.email,
    tg.telegram_id,
    tg.telegram_username,
    src.first_source,
    COALESCE(pay.purchase_count, 0) AS purchase_count,
    COALESCE(pay.ltv_rub, 0)::numeric(14,2) AS ltv_rub,
    pay.first_purchase_at,
    pay.last_purchase_at,
    acc.access_codes,
    u.first_seen_at,
    u.created_at,
    u.updated_at,
    u.data_origin
FROM users u
LEFT JOIN LATERAL (
    SELECT email_original AS email FROM user_emails
    WHERE user_id = u.id ORDER BY is_primary DESC, created_at ASC LIMIT 1
) pe ON true
LEFT JOIN LATERAL (
    SELECT platform_user_id AS telegram_id, username AS telegram_username
    FROM messenger_accounts WHERE user_id = u.id AND platform = 'telegram'
    ORDER BY created_at ASC LIMIT 1
) tg ON true
LEFT JOIN LATERAL (
    SELECT source_raw AS first_source FROM attribution_events
    WHERE user_id = u.id AND source_raw IS NOT NULL
    ORDER BY occurred_at NULLS LAST, created_at ASC LIMIT 1
) src ON true
LEFT JOIN LATERAL (
    SELECT
        count(*) FILTER (WHERE payment_status = 'paid') AS purchase_count,
        sum(amount) FILTER (WHERE payment_status = 'paid' AND currency = 'RUB') AS ltv_rub,
        min(paid_at) FILTER (WHERE payment_status = 'paid') AS first_purchase_at,
        max(paid_at) FILTER (WHERE payment_status = 'paid') AS last_purchase_at
    FROM payments WHERE user_id = u.id
) pay ON true
LEFT JOIN LATERAL (
    SELECT string_agg(DISTINCT r.code, ', ' ORDER BY r.code) AS access_codes
    FROM user_accesses ua JOIN resources r ON r.id = ua.resource_id
    WHERE ua.user_id = u.id AND ua.revoked_at IS NULL
      AND (ua.expires_at IS NULL OR ua.expires_at > now())
) acc ON true
WHERE u.merged_into_user_id IS NULL
"""


PAYMENTS_VIEW = """
CREATE OR REPLACE VIEW crm_payments_view AS
SELECT
    p.id AS payment_id,
    p.user_id,
    u.display_name,
    p.email_at_purchase,
    pr.code AS product_code,
    p.product_name_raw,
    p.amount,
    p.currency,
    p.payment_status,
    p.payment_system,
    p.external_order_id,
    p.external_payment_id,
    p.paid_at,
    p.source_event_at,
    p.source,
    p.created_at,
    pr.name AS product_name
FROM payments p
LEFT JOIN users u ON u.id = p.user_id
LEFT JOIN products pr ON pr.id = p.product_id
"""


OLD_USERS_VIEW = USERS_VIEW.rsplit(",\n    u.data_origin", 1)[0] + "\nFROM" + USERS_VIEW.rsplit("\nFROM", 1)[1]
OLD_PAYMENTS_VIEW = PAYMENTS_VIEW.rsplit(",\n    pr.name AS product_name", 1)[0] + "\nFROM" + PAYMENTS_VIEW.rsplit("\nFROM", 1)[1]


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("data_origin", sa.String(length=32), nullable=False, server_default="native"),
    )
    op.create_check_constraint(
        "ck_users_data_origin",
        "users",
        "data_origin IN ('legacy_import', 'native')",
    )
    op.execute("UPDATE users SET data_origin = 'legacy_import'")
    op.execute(USERS_VIEW)
    op.execute(PAYMENTS_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS crm_payments_view")
    op.execute("DROP VIEW IF EXISTS crm_users_view")
    op.execute(OLD_USERS_VIEW.replace("CREATE OR REPLACE", "CREATE"))
    op.execute(OLD_PAYMENTS_VIEW.replace("CREATE OR REPLACE", "CREATE"))
    op.drop_constraint("ck_users_data_origin", "users", type_="check")
    op.drop_column("users", "data_origin")
