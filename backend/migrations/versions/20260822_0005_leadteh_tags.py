"""Add LeadTeh contact provenance and manageable tag metadata.

Revision ID: 20260822_0005
Revises: 20260822_0004
"""

from alembic import op


revision = "20260822_0005"
down_revision = "20260822_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE user_phones (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            phone_original varchar(64) NOT NULL,
            phone_normalized varchar(32) NOT NULL,
            is_primary boolean NOT NULL DEFAULT true,
            source varchar(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_phone UNIQUE (user_id, phone_normalized)
        );
        CREATE INDEX ix_user_phones_user_id ON user_phones(user_id);
        CREATE INDEX ix_user_phones_phone_normalized ON user_phones(phone_normalized);

        ALTER TABLE tags ADD COLUMN category varchar(32) NOT NULL DEFAULT 'manual';
        ALTER TABLE tags ADD COLUMN status varchar(32) NOT NULL DEFAULT 'active';
        ALTER TABLE tags ADD COLUMN merged_into_tag_id uuid REFERENCES tags(id) ON DELETE SET NULL;
        ALTER TABLE tags ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
        ALTER TABLE tags ADD CONSTRAINT ck_tags_status
            CHECK (status IN ('active', 'ignored', 'merged'));
        CREATE INDEX ix_tags_category ON tags(category);
        CREATE INDEX ix_tags_status ON tags(status);
        CREATE INDEX ix_tags_merged_into_tag_id ON tags(merged_into_tag_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_tags_merged_into_tag_id;
        DROP INDEX IF EXISTS ix_tags_status;
        DROP INDEX IF EXISTS ix_tags_category;
        ALTER TABLE tags DROP CONSTRAINT IF EXISTS ck_tags_status;
        ALTER TABLE tags DROP COLUMN IF EXISTS updated_at;
        ALTER TABLE tags DROP COLUMN IF EXISTS merged_into_tag_id;
        ALTER TABLE tags DROP COLUMN IF EXISTS status;
        ALTER TABLE tags DROP COLUMN IF EXISTS category;
        DROP TABLE IF EXISTS user_phones;
    """)
