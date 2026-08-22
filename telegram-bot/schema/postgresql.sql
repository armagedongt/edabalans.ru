-- Проектная схема. Пока не применять к production.
CREATE SCHEMA IF NOT EXISTS telegram;

CREATE TYPE telegram.channel_kind AS ENUM ('telegram', 'max');
CREATE TYPE telegram.content_status AS ENUM ('draft', 'ready', 'archived');
CREATE TYPE telegram.version_status AS ENUM ('draft', 'published', 'retired');
CREATE TYPE telegram.step_kind AS ENUM ('message', 'delay', 'condition', 'action', 'finish');
CREATE TYPE telegram.run_status AS ENUM ('active', 'paused', 'completed', 'stopped', 'failed');
CREATE TYPE telegram.delivery_status AS ENUM ('pending', 'sending', 'sent', 'failed', 'cancelled');

CREATE TABLE telegram.archive_content_items (
    id uuid PRIMARY KEY,
    source_system text NOT NULL,
    source_scenario_id text NOT NULL,
    source_block_id text NOT NULL,
    scenario_name text,
    source_text text NOT NULL DEFAULT '',
    source_format text NOT NULL DEFAULT 'leadteh_mixed',
    media_kind text,
    imported_at timestamptz NOT NULL DEFAULT now(),
    source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_system, source_scenario_id, source_block_id)
);

CREATE TABLE telegram.archive_media_assets (
    id uuid PRIMARY KEY,
    archive_content_item_id uuid NOT NULL REFERENCES telegram.archive_content_items(id),
    media_kind text NOT NULL,
    filename text,
    mime_type text,
    byte_size bigint,
    source_url text,
    source_payload jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE telegram.content_items (
    id uuid PRIMARY KEY,
    origin_archive_item_id uuid REFERENCES telegram.archive_content_items(id),
    title text NOT NULL,
    body_source text NOT NULL DEFAULT '',
    source_format text NOT NULL DEFAULT 'telegram_html',
    status telegram.content_status NOT NULL DEFAULT 'draft',
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE telegram.content_revisions (
    id uuid PRIMARY KEY,
    content_item_id uuid NOT NULL REFERENCES telegram.content_items(id),
    revision_no integer NOT NULL,
    title text NOT NULL,
    body_source text NOT NULL,
    source_format text NOT NULL,
    editor_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (content_item_id, revision_no)
);

CREATE TABLE telegram.bot_instances (
    id uuid PRIMARY KEY,
    channel telegram.channel_kind NOT NULL,
    code text NOT NULL UNIQUE,
    display_name text NOT NULL,
    secret_env_name text NOT NULL,
    is_production boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT false
);

CREATE TABLE telegram.channel_assets (
    id uuid PRIMARY KEY,
    content_item_id uuid NOT NULL REFERENCES telegram.content_items(id),
    bot_instance_id uuid NOT NULL REFERENCES telegram.bot_instances(id),
    media_kind text NOT NULL,
    platform_file_id text,
    storage_key text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (content_item_id, bot_instance_id, media_kind)
);

CREATE TABLE telegram.sequences (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    description text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE telegram.sequence_versions (
    id uuid PRIMARY KEY,
    sequence_id uuid NOT NULL REFERENCES telegram.sequences(id),
    version_no integer NOT NULL,
    status telegram.version_status NOT NULL DEFAULT 'draft',
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    UNIQUE (sequence_id, version_no)
);

CREATE TABLE telegram.sequence_steps (
    id uuid PRIMARY KEY,
    sequence_version_id uuid NOT NULL REFERENCES telegram.sequence_versions(id),
    step_key text NOT NULL,
    kind telegram.step_kind NOT NULL,
    content_item_id uuid REFERENCES telegram.content_items(id),
    delay_seconds bigint,
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    channel_overrides jsonb NOT NULL DEFAULT '{}'::jsonb,
    position integer NOT NULL,
    UNIQUE (sequence_version_id, step_key),
    UNIQUE (sequence_version_id, position),
    CHECK ((kind <> 'message') OR content_item_id IS NOT NULL),
    CHECK ((kind <> 'delay') OR delay_seconds IS NOT NULL)
);

CREATE TABLE telegram.sequence_edges (
    id uuid PRIMARY KEY,
    sequence_version_id uuid NOT NULL REFERENCES telegram.sequence_versions(id),
    from_step_id uuid NOT NULL REFERENCES telegram.sequence_steps(id),
    to_step_id uuid NOT NULL REFERENCES telegram.sequence_steps(id),
    branch_key text NOT NULL DEFAULT 'next',
    condition jsonb NOT NULL DEFAULT '{}'::jsonb,
    priority integer NOT NULL DEFAULT 0,
    UNIQUE (from_step_id, branch_key, priority)
);

CREATE TABLE telegram.sequence_runs (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    sequence_version_id uuid NOT NULL REFERENCES telegram.sequence_versions(id),
    current_step_id uuid REFERENCES telegram.sequence_steps(id),
    status telegram.run_status NOT NULL DEFAULT 'active',
    next_action_at timestamptz,
    context jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_error text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE INDEX sequence_runs_due_idx
    ON telegram.sequence_runs (next_action_at)
    WHERE status = 'active';
CREATE INDEX sequence_runs_user_idx ON telegram.sequence_runs (user_id, started_at DESC);

CREATE TABLE telegram.step_deliveries (
    id uuid PRIMARY KEY,
    sequence_run_id uuid REFERENCES telegram.sequence_runs(id),
    step_id uuid REFERENCES telegram.sequence_steps(id),
    user_id uuid NOT NULL,
    bot_instance_id uuid NOT NULL REFERENCES telegram.bot_instances(id),
    delivery_kind text NOT NULL DEFAULT 'sequence',
    status telegram.delivery_status NOT NULL DEFAULT 'pending',
    idempotency_key text NOT NULL UNIQUE,
    platform_message_id text,
    attempt_count integer NOT NULL DEFAULT 0,
    scheduled_at timestamptz,
    sent_at timestamptz,
    last_error text,
    payload_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE telegram.tracking_links (
    id uuid PRIMARY KEY,
    token text NOT NULL UNIQUE,
    name text NOT NULL,
    source text,
    medium text,
    campaign text,
    action_configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE telegram.tracking_clicks (
    id uuid PRIMARY KEY,
    tracking_link_id uuid NOT NULL REFERENCES telegram.tracking_links(id),
    user_id uuid,
    messenger_account_id uuid,
    clicked_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE telegram.broadcasts (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    content_item_id uuid NOT NULL REFERENCES telegram.content_items(id),
    audience_filter jsonb NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    scheduled_at timestamptz,
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE telegram.broadcast_recipients (
    broadcast_id uuid NOT NULL REFERENCES telegram.broadcasts(id),
    user_id uuid NOT NULL,
    delivery_id uuid REFERENCES telegram.step_deliveries(id),
    PRIMARY KEY (broadcast_id, user_id)
);

CREATE TABLE telegram.conversations (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    bot_instance_id uuid NOT NULL REFERENCES telegram.bot_instances(id),
    last_message_at timestamptz,
    UNIQUE (user_id, bot_instance_id)
);

CREATE TABLE telegram.messages (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES telegram.conversations(id),
    direction text NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    kind text NOT NULL CHECK (kind IN ('manual', 'sequence', 'broadcast', 'system', 'user')),
    operator_id uuid,
    body_source text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    platform_message_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE telegram.microprojects (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    kind text NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
