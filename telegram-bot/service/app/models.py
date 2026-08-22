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


class TrackingEvent(Base):
    __tablename__ = "tg_tracking_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tracking_link_id: Mapped[str | None] = mapped_column(ForeignKey("tg_tracking_links.id"), index=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("tg_contacts.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


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
