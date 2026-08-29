"""Add the unified knowledge registry.

Revision ID: 20260829_0030
Revises: 20260829_0029
"""

from alembic import op


revision = "20260829_0030"
down_revision = "20260829_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE knowledge_resources (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            resource_key varchar(255) NOT NULL UNIQUE,
            title text NOT NULL,
            contour varchar(32) NOT NULL,
            resource_kind varchar(64) NOT NULL,
            role varchar(32) NOT NULL,
            state varchar(32) NOT NULL,
            storage_kind varchar(32) NOT NULL,
            canonical_uri text NOT NULL,
            owner_module varchar(128) NOT NULL,
            access_level varchar(32) NOT NULL,
            person_reference text,
            source_author text,
            source_date timestamptz,
            latest_version_id uuid,
            metadata_json json NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_knowledge_resources_contour_kind
            ON knowledge_resources(contour, resource_kind);
        CREATE INDEX ix_knowledge_resources_state ON knowledge_resources(state);
        CREATE INDEX ix_knowledge_resources_access ON knowledge_resources(access_level);

        CREATE TABLE knowledge_resource_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            resource_id uuid NOT NULL REFERENCES knowledge_resources(id) ON DELETE CASCADE,
            version_no integer NOT NULL,
            content_hash varchar(64) NOT NULL,
            text_content text NOT NULL,
            provenance json NOT NULL DEFAULT '{}',
            created_by varchar(255) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_knowledge_resource_version_no UNIQUE(resource_id, version_no),
            CONSTRAINT uq_knowledge_resource_version_hash UNIQUE(resource_id, content_hash)
        );
        CREATE INDEX ix_knowledge_resource_versions_resource_id
            ON knowledge_resource_versions(resource_id);
        ALTER TABLE knowledge_resources
            ADD CONSTRAINT fk_knowledge_resources_latest_version
            FOREIGN KEY(latest_version_id)
            REFERENCES knowledge_resource_versions(id) ON DELETE SET NULL;

        CREATE TABLE knowledge_relations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_resource_id uuid NOT NULL REFERENCES knowledge_resources(id) ON DELETE CASCADE,
            target_resource_id uuid NOT NULL REFERENCES knowledge_resources(id) ON DELETE CASCADE,
            relation_type varchar(48) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'active',
            metadata_json json NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_knowledge_relation
                UNIQUE(source_resource_id, target_resource_id, relation_type),
            CONSTRAINT ck_knowledge_relation_not_self
                CHECK(source_resource_id <> target_resource_id)
        );
        CREATE INDEX ix_knowledge_relations_source_resource_id
            ON knowledge_relations(source_resource_id);
        CREATE INDEX ix_knowledge_relations_target
            ON knowledge_relations(target_resource_id, relation_type);

        CREATE TABLE knowledge_review_items (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            review_key varchar(255) NOT NULL UNIQUE,
            review_kind varchar(48) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'pending',
            title text NOT NULL,
            resource_ids json NOT NULL DEFAULT '[]',
            details_json json NOT NULL DEFAULT '{}',
            decision_json json NOT NULL DEFAULT '{}',
            decided_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_knowledge_review_status_kind
            ON knowledge_review_items(status, review_kind);

        CREATE TABLE knowledge_usage_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            resource_id uuid REFERENCES knowledge_resources(id) ON DELETE SET NULL,
            source_uri text NOT NULL,
            task_key varchar(255) NOT NULL,
            destination text NOT NULL,
            usage_kind varchar(48) NOT NULL,
            excerpt_reference text,
            output_uri text,
            metadata_json json NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_knowledge_usage_resource_created
            ON knowledge_usage_events(resource_id, created_at);
        CREATE INDEX ix_knowledge_usage_events_source_uri
            ON knowledge_usage_events(source_uri);
        CREATE INDEX ix_knowledge_usage_task ON knowledge_usage_events(task_key);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS knowledge_usage_events;
        DROP TABLE IF EXISTS knowledge_review_items;
        DROP TABLE IF EXISTS knowledge_relations;
        ALTER TABLE knowledge_resources
            DROP CONSTRAINT IF EXISTS fk_knowledge_resources_latest_version;
        DROP TABLE IF EXISTS knowledge_resource_versions;
        DROP TABLE IF EXISTS knowledge_resources;
    """)
