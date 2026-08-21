"""Create the CRM/Core schema and read-only operational views.

Revision ID: 20260822_0002
Revises: 20260821_0001
Create Date: 2026-08-22
"""

from alembic import op


revision = "20260822_0002"
down_revision = "20260821_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = """
        CREATE TABLE users (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            display_name varchar(255),
            status varchar(32) NOT NULL DEFAULT 'active',
            first_seen_at timestamptz,
            merged_into_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE user_emails (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            email_original varchar(320) NOT NULL,
            email_normalized varchar(320) NOT NULL UNIQUE,
            is_primary boolean NOT NULL DEFAULT true,
            verification_status varchar(32) NOT NULL DEFAULT 'legacy_unverified',
            source varchar(64) NOT NULL,
            first_seen_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_user_emails_user_id ON user_emails(user_id);

        CREATE TABLE messenger_accounts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            platform varchar(32) NOT NULL,
            platform_user_id varchar(128),
            username varchar(255),
            first_name varchar(255),
            first_seen_at timestamptz,
            last_seen_at timestamptz,
            linked_at timestamptz,
            source varchar(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_messenger_identity UNIQUE(platform, platform_user_id)
        );
        CREATE INDEX ix_messenger_accounts_user_id ON messenger_accounts(user_id);

        CREATE TABLE products (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(80) NOT NULL UNIQUE,
            name varchar(255) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'active',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE product_aliases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            product_id uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            source varchar(64) NOT NULL,
            raw_name_exact text NOT NULL,
            active_from timestamptz,
            active_to timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_product_alias_source_name UNIQUE(source, raw_name_exact)
        );
        CREATE INDEX ix_product_aliases_product_id ON product_aliases(product_id);

        CREATE TABLE resources (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(80) NOT NULL UNIQUE,
            name varchar(255) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'active',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE product_access_rules (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            product_id uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            resource_id uuid NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
            effective_from timestamptz,
            effective_to timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_product_access_rule UNIQUE(product_id, resource_id, effective_from)
        );
        CREATE INDEX ix_product_access_rules_product_id ON product_access_rules(product_id);
        CREATE INDEX ix_product_access_rules_resource_id ON product_access_rules(resource_id);

        CREATE TABLE import_batches (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source varchar(128) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'running',
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            summary json
        );

        CREATE TABLE payments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            product_id uuid REFERENCES products(id) ON DELETE SET NULL,
            import_batch_id uuid REFERENCES import_batches(id) ON DELETE SET NULL,
            source varchar(64) NOT NULL,
            external_order_id varchar(255),
            external_payment_id varchar(255),
            external_request_id varchar(255),
            email_at_purchase varchar(320),
            product_name_raw text NOT NULL,
            amount numeric(14,2) NOT NULL,
            currency varchar(3) NOT NULL DEFAULT 'RUB',
            payment_status varchar(32) NOT NULL,
            payment_system varchar(64),
            source_event_at timestamptz,
            paid_at timestamptz,
            paid_at_is_estimated boolean NOT NULL DEFAULT false,
            external_form_id varchar(255),
            form_name_raw varchar(255),
            referer_raw text,
            landing_url text,
            raw_payload json,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_payment_source_order UNIQUE(source, external_order_id),
            CONSTRAINT uq_payment_source_payment UNIQUE(source, external_payment_id)
        );
        CREATE INDEX ix_payments_user_id ON payments(user_id);
        CREATE INDEX ix_payments_product_id ON payments(product_id);
        CREATE INDEX ix_payments_user_paid_at ON payments(user_id, paid_at);

        CREATE TABLE user_accesses (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            resource_id uuid NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
            source_payment_id uuid REFERENCES payments(id) ON DELETE SET NULL,
            source varchar(64) NOT NULL,
            granted_at timestamptz NOT NULL,
            expires_at timestamptz,
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_access_payment_resource UNIQUE(user_id, resource_id, source_payment_id)
        );
        CREATE INDEX ix_user_accesses_user_id ON user_accesses(user_id);
        CREATE INDEX ix_user_accesses_resource_id ON user_accesses(resource_id);

        CREATE TABLE attribution_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            import_batch_id uuid REFERENCES import_batches(id) ON DELETE SET NULL,
            event_type varchar(64) NOT NULL,
            source_raw text,
            utm_source varchar(255),
            utm_medium varchar(255),
            utm_campaign varchar(255),
            utm_content varchar(255),
            utm_term varchar(255),
            ref_code varchar(255),
            landing_url text,
            occurred_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_attribution_events_user_id ON attribution_events(user_id);

        CREATE TABLE tags (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(80) NOT NULL UNIQUE,
            name varchar(255) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE user_tags (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tag_id uuid NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            source varchar(64) NOT NULL DEFAULT 'manual',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_tag UNIQUE(user_id, tag_id)
        );
        CREATE INDEX ix_user_tags_user_id ON user_tags(user_id);
        CREATE INDEX ix_user_tags_tag_id ON user_tags(tag_id);

        CREATE TABLE client_notes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            body text NOT NULL,
            author varchar(255) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_client_notes_user_id ON client_notes(user_id);

        CREATE TABLE legacy_import_records (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            import_batch_id uuid NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
            source varchar(128) NOT NULL,
            source_row_number integer NOT NULL,
            row_hash varchar(64) NOT NULL,
            external_record_id varchar(255),
            status varchar(32) NOT NULL,
            user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            payment_id uuid REFERENCES payments(id) ON DELETE SET NULL,
            reason text,
            raw_payload json,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_legacy_source_row_hash UNIQUE(source, row_hash)
        );
        CREATE INDEX ix_legacy_import_records_batch_id ON legacy_import_records(import_batch_id);

        CREATE TABLE user_merge_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            from_user_id uuid NOT NULL REFERENCES users(id),
            to_user_id uuid NOT NULL REFERENCES users(id),
            reason text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_user_merge_events_from_user_id ON user_merge_events(from_user_id);
        CREATE INDEX ix_user_merge_events_to_user_id ON user_merge_events(to_user_id);

        CREATE VIEW crm_users_view AS
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
            u.updated_at
        FROM users u
        LEFT JOIN LATERAL (
            SELECT email_original AS email
            FROM user_emails
            WHERE user_id = u.id
            ORDER BY is_primary DESC, created_at ASC
            LIMIT 1
        ) pe ON true
        LEFT JOIN LATERAL (
            SELECT platform_user_id AS telegram_id, username AS telegram_username
            FROM messenger_accounts
            WHERE user_id = u.id AND platform = 'telegram'
            ORDER BY created_at ASC
            LIMIT 1
        ) tg ON true
        LEFT JOIN LATERAL (
            SELECT source_raw AS first_source
            FROM attribution_events
            WHERE user_id = u.id AND source_raw IS NOT NULL
            ORDER BY occurred_at NULLS LAST, created_at ASC
            LIMIT 1
        ) src ON true
        LEFT JOIN LATERAL (
            SELECT
                count(*) FILTER (WHERE payment_status = 'paid') AS purchase_count,
                sum(amount) FILTER (WHERE payment_status = 'paid' AND currency = 'RUB') AS ltv_rub,
                min(paid_at) FILTER (WHERE payment_status = 'paid') AS first_purchase_at,
                max(paid_at) FILTER (WHERE payment_status = 'paid') AS last_purchase_at
            FROM payments
            WHERE user_id = u.id
        ) pay ON true
        LEFT JOIN LATERAL (
            SELECT string_agg(DISTINCT r.code, ', ' ORDER BY r.code) AS access_codes
            FROM user_accesses ua
            JOIN resources r ON r.id = ua.resource_id
            WHERE ua.user_id = u.id
              AND ua.revoked_at IS NULL
              AND (ua.expires_at IS NULL OR ua.expires_at > now())
        ) acc ON true
        WHERE u.merged_into_user_id IS NULL;

        CREATE VIEW crm_payments_view AS
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
            p.created_at
        FROM payments p
        LEFT JOIN users u ON u.id = p.user_id
        LEFT JOIN products pr ON pr.id = p.product_id;
        """
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    sql = """
        DROP VIEW IF EXISTS crm_payments_view;
        DROP VIEW IF EXISTS crm_users_view;
        DROP TABLE IF EXISTS user_merge_events;
        DROP TABLE IF EXISTS legacy_import_records;
        DROP TABLE IF EXISTS client_notes;
        DROP TABLE IF EXISTS user_tags;
        DROP TABLE IF EXISTS tags;
        DROP TABLE IF EXISTS attribution_events;
        DROP TABLE IF EXISTS user_accesses;
        DROP TABLE IF EXISTS payments;
        DROP TABLE IF EXISTS import_batches;
        DROP TABLE IF EXISTS product_access_rules;
        DROP TABLE IF EXISTS resources;
        DROP TABLE IF EXISTS product_aliases;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS messenger_accounts;
        DROP TABLE IF EXISTS user_emails;
        DROP TABLE IF EXISTS users;
        """
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)
