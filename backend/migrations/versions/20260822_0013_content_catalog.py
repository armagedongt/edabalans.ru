"""Add the text-first content catalog.

Revision ID: 20260822_0013
Revises: 20260822_0012
"""

from alembic import op


revision = "20260822_0013"
down_revision = "20260822_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE content_sources (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            platform varchar(32) NOT NULL,
            account_key varchar(255) NOT NULL,
            display_name varchar(255) NOT NULL,
            canonical_url text NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'active',
            last_synced_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_content_source_account UNIQUE(platform, account_key)
        );

        CREATE TABLE content_items (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id uuid NOT NULL REFERENCES content_sources(id) ON DELETE RESTRICT,
            external_id varchar(128) NOT NULL,
            canonical_url text NOT NULL,
            title text NOT NULL,
            author_name varchar(255),
            published_at timestamptz,
            source_updated_at timestamptz,
            status varchar(32) NOT NULL DEFAULT 'published',
            latest_version_id uuid,
            source_tags json NOT NULL DEFAULT '[]',
            ending_text text,
            ending_kind varchar(32),
            cta_text text,
            cta_url text,
            recommendations_status varchar(32) NOT NULL DEFAULT 'review',
            review_status varchar(32) NOT NULL DEFAULT 'pending',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_content_item_external UNIQUE(source_id, external_id)
        );
        CREATE INDEX ix_content_items_source_id ON content_items(source_id);
        CREATE INDEX ix_content_items_published_at ON content_items(published_at);

        CREATE TABLE content_item_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            version_no integer NOT NULL,
            content_hash varchar(64) NOT NULL,
            text_content text NOT NULL,
            blocks json NOT NULL DEFAULT '[]',
            parser_version varchar(64) NOT NULL,
            source_updated_at timestamptz,
            imported_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_content_item_version_no UNIQUE(item_id, version_no),
            CONSTRAINT uq_content_item_version_hash UNIQUE(item_id, content_hash)
        );
        CREATE INDEX ix_content_item_versions_item_id ON content_item_versions(item_id);
        ALTER TABLE content_items
            ADD CONSTRAINT fk_content_items_latest_version
            FOREIGN KEY (latest_version_id) REFERENCES content_item_versions(id) ON DELETE SET NULL;

        CREATE TABLE content_media (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            version_id uuid NOT NULL REFERENCES content_item_versions(id) ON DELETE CASCADE,
            media_type varchar(32) NOT NULL,
            source_url text NOT NULL,
            preview_url text,
            position integer NOT NULL,
            metadata_json json NOT NULL DEFAULT '{}',
            CONSTRAINT uq_content_media_position_url UNIQUE(version_id, position, source_url)
        );
        CREATE INDEX ix_content_media_item_id ON content_media(item_id);
        CREATE INDEX ix_content_media_version_id ON content_media(version_id);

        CREATE TABLE content_links (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            version_id uuid NOT NULL REFERENCES content_item_versions(id) ON DELETE CASCADE,
            visible_text text,
            wrapped_url text NOT NULL,
            target_url text NOT NULL,
            domain varchar(255),
            link_type varchar(32) NOT NULL DEFAULT 'other',
            is_cta boolean NOT NULL DEFAULT false,
            ignored_for_generation boolean NOT NULL DEFAULT false,
            position integer NOT NULL
        );
        CREATE INDEX ix_content_links_item_id ON content_links(item_id);
        CREATE INDEX ix_content_links_version_id ON content_links(version_id);

        CREATE TABLE content_metric_snapshots (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            captured_at timestamptz NOT NULL DEFAULT now(),
            metric_source varchar(32) NOT NULL,
            views integer,
            rating integer,
            pluses integer,
            minuses integer,
            saves integer,
            comments_reported integer,
            emotions json NOT NULL DEFAULT '[]'
        );
        CREATE INDEX ix_content_metric_snapshots_item_id ON content_metric_snapshots(item_id);
        CREATE INDEX ix_content_metric_item_captured
            ON content_metric_snapshots(item_id, captured_at);

        CREATE TABLE content_import_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id uuid REFERENCES content_sources(id) ON DELETE SET NULL,
            mode varchar(32) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'running',
            parser_version varchar(64) NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            summary json NOT NULL DEFAULT '{}'
        );
        CREATE INDEX ix_content_import_runs_source_id ON content_import_runs(source_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS content_import_runs;
        DROP TABLE IF EXISTS content_metric_snapshots;
        DROP TABLE IF EXISTS content_links;
        DROP TABLE IF EXISTS content_media;
        ALTER TABLE content_items DROP CONSTRAINT IF EXISTS fk_content_items_latest_version;
        DROP TABLE IF EXISTS content_item_versions;
        DROP TABLE IF EXISTS content_items;
        DROP TABLE IF EXISTS content_sources;
    """)
