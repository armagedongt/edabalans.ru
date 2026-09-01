from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def uuid_text() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BotInstance(TimestampMixin, Base):
    __tablename__ = "tg_bot_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_env_name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_production: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Contact(TimestampMixin, Base):
    __tablename__ = "tg_contacts"
    __table_args__ = (UniqueConstraint("bot_instance_id", "telegram_user_id", name="uq_tg_contact_bot_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    bot_instance_id: Mapped[str] = mapped_column(ForeignKey("tg_bot_instances.id"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), index=True)
    telegram_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    language_code: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    first_source_token: Mapped[str | None] = mapped_column(String(64))
    last_source_token: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContentItem(TimestampMixin, Base):
    __tablename__ = "tg_content_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body_source: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_format: Mapped[str] = mapped_column(String(32), default="telegram_html", nullable=False)
    purpose: Mapped[str] = mapped_column(Text, default="", nullable=False)
    writer_brief: Mapped[str] = mapped_column(Text, default="", nullable=False)
    editorial_status: Mapped[str] = mapped_column(String(32), default="needs_writing", nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    media_kind: Mapped[str | None] = mapped_column(String(32))
    media_path: Mapped[str | None] = mapped_column(Text)
    telegram_file_id: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    origin_system: Mapped[str | None] = mapped_column(String(64))
    origin_scenario_id: Mapped[str | None] = mapped_column(String(64))
    origin_scenario_name: Mapped[str | None] = mapped_column(String(255))
    origin_block_id: Mapped[str | None] = mapped_column(String(64))


class Sequence(TimestampMixin, Base):
    __tablename__ = "tg_sequences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)


class SequenceVersion(TimestampMixin, Base):
    __tablename__ = "tg_sequence_versions"
    __table_args__ = (UniqueConstraint("sequence_id", "version_no", name="uq_tg_sequence_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("tg_sequences.id"), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SequenceStep(TimestampMixin, Base):
    __tablename__ = "tg_sequence_steps"
    __table_args__ = (
        UniqueConstraint("sequence_version_id", "step_key", name="uq_tg_step_key"),
        UniqueConstraint("sequence_version_id", "position", name="uq_tg_step_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    sequence_version_id: Mapped[str] = mapped_column(ForeignKey("tg_sequence_versions.id"), nullable=False, index=True)
    step_key: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    content_item_id: Mapped[str | None] = mapped_column(ForeignKey("tg_content_items.id"))
    delay_seconds: Mapped[int | None] = mapped_column(Integer)
    next_step_key: Mapped[str | None] = mapped_column(String(120))
    configuration: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SequenceEdge(TimestampMixin, Base):
    __tablename__ = "tg_sequence_edges"
    __table_args__ = (
        UniqueConstraint(
            "sequence_version_id",
            "from_step_key",
            "branch_key",
            "priority",
            name="uq_tg_sequence_edge_branch",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    sequence_version_id: Mapped[str] = mapped_column(ForeignKey("tg_sequence_versions.id"), nullable=False, index=True)
    from_step_key: Mapped[str] = mapped_column(String(120), nullable=False)
    to_step_key: Mapped[str | None] = mapped_column(String(120))
    target_sequence_code: Mapped[str | None] = mapped_column(String(100))
    branch_key: Mapped[str] = mapped_column(String(40), default="default", nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))
    condition: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BotRoute(TimestampMixin, Base):
    __tablename__ = "tg_bot_routes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trigger_value: Mapped[str] = mapped_column(String(255), nullable=False)
    source_component: Mapped[str] = mapped_column(String(120), nullable=False)
    target_sequence_code: Mapped[str] = mapped_column(String(100), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SequenceRun(TimestampMixin, Base):
    __tablename__ = "tg_sequence_runs"
    __table_args__ = (Index("ix_tg_runs_due", "status", "next_action_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    contact_id: Mapped[str] = mapped_column(ForeignKey("tg_contacts.id"), nullable=False, index=True)
    sequence_version_id: Mapped[str] = mapped_column(ForeignKey("tg_sequence_versions.id"), nullable=False)
    current_step_key: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    time_scale: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StepDelivery(Base):
    __tablename__ = "tg_step_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    run_id: Mapped[str] = mapped_column(ForeignKey("tg_sequence_runs.id"), nullable=False, index=True)
    step_key: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    platform_message_id: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    payload_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UpdateReceipt(Base):
    __tablename__ = "tg_update_receipts"

    update_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bot_instance_id: Mapped[str] = mapped_column(ForeignKey("tg_bot_instances.id"), nullable=False)
    update_type: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TrackingLink(TimestampMixin, Base):
    __tablename__ = "tg_tracking_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    placement: Mapped[str] = mapped_column(String(255), nullable=False)
    campaign: Mapped[str | None] = mapped_column(String(255))
    target_sequence_code: Mapped[str] = mapped_column(String(100), default="prepurchase_masterclass", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="Ссылка", nullable=False)
    target_kind: Mapped[str] = mapped_column(String(32), default="bot_start", nullable=False)
    route_kind: Mapped[str] = mapped_column(String(32), default="root", nullable=False)
    target_step_key: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(320))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrackingLinkAlias(Base):
    __tablename__ = "tg_tracking_link_aliases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tracking_link_id: Mapped[str] = mapped_column(ForeignKey("tg_tracking_links.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    alias_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    telegram_invite_url: Mapped[str | None] = mapped_column(Text)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    creates_join_request: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrackingLinkTag(Base):
    __tablename__ = "tg_tracking_link_tags"

    tracking_link_id: Mapped[str] = mapped_column(ForeignKey("tg_tracking_links.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("tags.id", ondelete="RESTRICT"), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32), default="other", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UtmTagRule(TimestampMixin, Base):
    __tablename__ = "tg_utm_tag_rules"
    __table_args__ = (UniqueConstraint("parameter_name", "normalized_value", name="uq_tg_utm_rule"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    parameter_name: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    tag_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("tags.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(320))


class TrackingSession(Base):
    __tablename__ = "tg_tracking_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    start_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    tracking_link_id: Mapped[str] = mapped_column(ForeignKey("tg_tracking_links.id", ondelete="CASCADE"), nullable=False)
    alias_id: Mapped[str] = mapped_column(ForeignKey("tg_tracking_link_aliases.id", ondelete="CASCADE"), nullable=False)
    raw_query: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    resolved_tag_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrackingEvent(Base):
    __tablename__ = "tg_tracking_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tracking_link_id: Mapped[str | None] = mapped_column(ForeignKey("tg_tracking_links.id"), index=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("tg_contacts.id"), index=True)
    alias_id: Mapped[str | None] = mapped_column(ForeignKey("tg_tracking_link_aliases.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    telegram_user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    deduplication_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CrmUser(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    display_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    data_origin: Mapped[str] = mapped_column(String(32), default="native", nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CrmMessengerAccount(Base):
    __tablename__ = "messenger_accounts"
    __table_args__ = (UniqueConstraint("platform", "platform_user_id", name="uq_messenger_identity"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscription_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    subscription_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    main_scenario_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(64), default="telegram_bot", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CrmTag(Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    merged_into_tag_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("tags.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CrmUserTag(Base):
    __tablename__ = "user_tags"
    __table_args__ = (UniqueConstraint("user_id", "tag_id", name="uq_user_tag"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tag_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="telegram_first_touch", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CrmAttributionEvent(Base):
    __tablename__ = "attribution_events"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_raw: Mapped[str | None] = mapped_column(Text)
    utm_source: Mapped[str | None] = mapped_column(String(255))
    utm_medium: Mapped[str | None] = mapped_column(String(255))
    utm_campaign: Mapped[str | None] = mapped_column(String(255))
    utm_content: Mapped[str | None] = mapped_column(String(255))
    utm_term: Mapped[str | None] = mapped_column(String(255))
    ref_code: Mapped[str | None] = mapped_column(String(255))
    landing_url: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserVariable(TimestampMixin, Base):
    __tablename__ = "tg_user_variables"
    __table_args__ = (UniqueConstraint("contact_id", "key", name="uq_tg_contact_variable"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    contact_id: Mapped[str] = mapped_column(ForeignKey("tg_contacts.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ManualMessage(Base):
    __tablename__ = "tg_manual_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    contact_id: Mapped[str] = mapped_column(ForeignKey("tg_contacts.id"), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    body_source: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    operator_email: Mapped[str | None] = mapped_column(String(320))
    platform_message_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MasterclassNotification(Base):
    __tablename__ = "masterclass_notifications"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uuid_text)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    event_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False))
    notification_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    content_code: Mapped[str | None] = mapped_column(String(120))
    deduplication_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MessengerLinkToken(Base):
    __tablename__ = "messenger_link_tokens"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uuid_text)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TelegramLoginAttempt(Base):
    __tablename__ = "telegram_login_attempts"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    nonce_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    verification_code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Broadcast(TimestampMixin, Base):
    __tablename__ = "tg_broadcasts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_item_id: Mapped[str] = mapped_column(ForeignKey("tg_content_items.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    segment: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(320))


class BroadcastRecipient(Base):
    __tablename__ = "tg_broadcast_recipients"
    __table_args__ = (UniqueConstraint("broadcast_id", "contact_id", name="uq_tg_broadcast_contact"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    broadcast_id: Mapped[str] = mapped_column(ForeignKey("tg_broadcasts.id"), nullable=False, index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("tg_contacts.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    platform_message_id: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
