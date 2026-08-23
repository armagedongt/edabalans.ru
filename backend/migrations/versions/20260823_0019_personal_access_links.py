"""Add owner-created personal access links and course unlock policies.

Revision ID: 20260823_0019
Revises: 20260823_0018
"""

from alembic import op


revision = "20260823_0019"
down_revision = "20260823_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE personal_access_links (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash varchar(64) NOT NULL UNIQUE,
            mode varchar(16) NOT NULL,
            resource_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
            unlock_modes jsonb NOT NULL DEFAULT '{}'::jsonb,
            standard_amount numeric(14,2),
            final_amount numeric(14,2) NOT NULL,
            currency varchar(3) NOT NULL DEFAULT 'RUB',
            status varchar(32) NOT NULL DEFAULT 'active',
            expires_at timestamptz,
            checkout_id uuid UNIQUE REFERENCES offer_checkouts(id) ON DELETE SET NULL,
            created_by varchar(255) NOT NULL,
            telegram_text text NOT NULL,
            resolved_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_personal_access_link_mode CHECK (mode IN ('free','paid')),
            CONSTRAINT ck_personal_access_link_status CHECK (status IN ('active','claimed','paid','expired','cancelled')),
            CONSTRAINT ck_personal_access_link_amount CHECK (final_amount >= 0),
            CONSTRAINT ck_personal_access_link_mode_amount CHECK (
                (mode = 'free' AND final_amount = 0) OR (mode = 'paid' AND final_amount > 0)
            )
        );
        CREATE INDEX ix_personal_access_links_user ON personal_access_links(user_id);

        CREATE TABLE user_course_policies (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            resource_id uuid NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
            unlock_mode varchar(32) NOT NULL DEFAULT 'paced',
            source varchar(64) NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_course_policy UNIQUE (user_id, resource_id),
            CONSTRAINT ck_user_course_unlock_mode CHECK (unlock_mode IN ('paced','fully_unlocked'))
        );
        CREATE INDEX ix_user_course_policies_user ON user_course_policies(user_id);
        CREATE INDEX ix_user_course_policies_resource ON user_course_policies(resource_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_course_policies;")
    op.execute("DROP TABLE IF EXISTS personal_access_links;")
