"""Add editable families and source-neutral catalog metadata.

Revision ID: 20260829_0029
Revises: 20260828_0028
"""

from alembic import op


revision = "20260829_0029"
down_revision = "20260828_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE content_items
            ADD COLUMN catalog_key varchar(255),
            ADD COLUMN manifestation_kind varchar(32) NOT NULL DEFAULT 'post',
            ADD COLUMN editorial_status varchar(32) NOT NULL DEFAULT 'active',
            ADD COLUMN purpose varchar(64) NOT NULL DEFAULT 'ordinary_content',
            ADD COLUMN sales_level varchar(32) NOT NULL DEFAULT 'none',
            ADD COLUMN meanings json NOT NULL DEFAULT '[]',
            ADD COLUMN topics json NOT NULL DEFAULT '[]',
            ADD COLUMN primary_function varchar(80),
            ADD COLUMN variant_label text NOT NULL DEFAULT '',
            ADD COLUMN metadata_json json NOT NULL DEFAULT '{}';
        ALTER TABLE content_items
            ADD CONSTRAINT uq_content_item_catalog_key UNIQUE (catalog_key);

        ALTER TABLE content_item_versions
            ADD COLUMN editorial_metadata json NOT NULL DEFAULT '{}';

        CREATE TABLE content_families (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            family_key varchar(255) NOT NULL UNIQUE,
            status varchar(32) NOT NULL DEFAULT 'active',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE content_family_memberships (
            item_id uuid PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
            family_id uuid NOT NULL REFERENCES content_families(id) ON DELETE CASCADE,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_content_family_memberships_family_id
            ON content_family_memberships(family_id);

        CREATE TABLE content_family_candidates (
            pair_key varchar(511) PRIMARY KEY,
            left_item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            right_item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            method varchar(64) NOT NULL,
            shared_tokens integer,
            status varchar(32) NOT NULL DEFAULT 'pending',
            decided_at timestamptz,
            metadata_json json NOT NULL DEFAULT '{}',
            CONSTRAINT uq_content_family_candidate_pair UNIQUE(left_item_id, right_item_id)
        );
        CREATE INDEX ix_content_family_candidate_status
            ON content_family_candidates(status);
        CREATE INDEX ix_content_family_candidates_left_item_id
            ON content_family_candidates(left_item_id);
        CREATE INDEX ix_content_family_candidates_right_item_id
            ON content_family_candidates(right_item_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS content_family_candidates;
        DROP TABLE IF EXISTS content_family_memberships;
        DROP TABLE IF EXISTS content_families;
        ALTER TABLE content_item_versions DROP COLUMN IF EXISTS editorial_metadata;
        ALTER TABLE content_items
            DROP CONSTRAINT IF EXISTS uq_content_item_catalog_key,
            DROP COLUMN IF EXISTS metadata_json,
            DROP COLUMN IF EXISTS variant_label,
            DROP COLUMN IF EXISTS primary_function,
            DROP COLUMN IF EXISTS topics,
            DROP COLUMN IF EXISTS meanings,
            DROP COLUMN IF EXISTS sales_level,
            DROP COLUMN IF EXISTS purpose,
            DROP COLUMN IF EXISTS editorial_status,
            DROP COLUMN IF EXISTS manifestation_kind,
            DROP COLUMN IF EXISTS catalog_key;
    """)
