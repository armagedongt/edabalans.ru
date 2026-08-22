from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    display_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    data_origin: Mapped[str] = mapped_column(
        String(32), default="native", server_default=text("'native'"), nullable=False
    )
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_into_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    access_review_status: Mapped[str] = mapped_column(
        String(32), default="not_required", server_default=text("'not_required'"), nullable=False
    )
    access_review_note: Mapped[str | None] = mapped_column(Text)
    access_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tilda_access_status: Mapped[str] = mapped_column(
        String(32), default="not_checked", server_default=text("'not_checked'"), nullable=False
    )


class UserEmail(Base):
    __tablename__ = "user_emails"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    email_original: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(32), default="legacy_unverified", nullable=False
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserPhone(Base):
    __tablename__ = "user_phones"
    __table_args__ = (
        UniqueConstraint("user_id", "phone_normalized", name="uq_user_phone"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    phone_original: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_normalized: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MessengerAccount(Base):
    __tablename__ = "messenger_accounts"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_messenger_identity"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscription_status: Mapped[str] = mapped_column(
        String(32), default="unknown", server_default=text("'unknown'"), nullable=False
    )
    subscription_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    main_scenario_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class ProductAlias(Base):
    __tablename__ = "product_aliases"
    __table_args__ = (
        UniqueConstraint("source", "raw_name_exact", name="uq_product_alias_source_name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_name_exact: Mapped[str] = mapped_column(Text, nullable=False)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Resource(TimestampMixin, Base):
    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class ProductAccessRule(Base):
    __tablename__ = "product_access_rules"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "resource_id", "effective_from", name="uq_product_access_rule"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), index=True
    )
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = uuid_pk()
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict | None] = mapped_column(JSON)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("source", "external_order_id", name="uq_payment_source_order"),
        UniqueConstraint("source", "external_payment_id", name="uq_payment_source_payment"),
        Index("ix_payments_user_paid_at", "user_id", "paid_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_order_id: Mapped[str | None] = mapped_column(String(255))
    external_payment_id: Mapped[str | None] = mapped_column(String(255))
    external_request_id: Mapped[str | None] = mapped_column(String(255))
    email_at_purchase: Mapped[str | None] = mapped_column(String(320))
    product_name_raw: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    amount_is_estimated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(32), default="not_required", server_default=text("'not_required'"), nullable=False
    )
    payment_system: Mapped[str | None] = mapped_column(String(64))
    source_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at_is_estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    external_form_id: Mapped[str | None] = mapped_column(String(255))
    form_name_raw: Mapped[str | None] = mapped_column(String(255))
    referer_raw: Mapped[str | None] = mapped_column(Text)
    landing_url: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserAccess(Base):
    __tablename__ = "user_accesses"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "resource_id", "source_payment_id", name="uq_access_payment_resource"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), index=True
    )
    source_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AttributionEvent(Base):
    __tablename__ = "attribution_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    merged_into_tag_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tags.id", ondelete="SET NULL")
    )
    audit_action: Mapped[str | None] = mapped_column(String(64))
    audit_reason: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserTag(Base):
    __tablename__ = "user_tags"
    __table_args__ = (UniqueConstraint("user_id", "tag_id", name="uq_user_tag"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(64), default="manual", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClientNote(Base):
    __tablename__ = "client_notes"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LegacyImportRecord(Base):
    __tablename__ = "legacy_import_records"
    __table_args__ = (
        UniqueConstraint("source", "row_hash", name="uq_legacy_source_row_hash"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    source_row_number: Mapped[int] = mapped_column(nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    external_record_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserMergeEvent(Base):
    __tablename__ = "user_merge_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    from_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    to_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DqsState(TimestampMixin, Base):
    __tablename__ = "dqs_states"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    start_date: Mapped[str | None] = mapped_column(String(10))
    days: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="app", nullable=False)


class StrengthState(TimestampMixin, Base):
    __tablename__ = "strength_states"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    workout_types: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    hidden_exercises: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    workouts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="app", nullable=False)


class StrengthExercise(TimestampMixin, Base):
    __tablename__ = "strength_exercises"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MetabolismState(TimestampMixin, Base):
    __tablename__ = "metabolism_states"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    variants: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    active_variant: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    formula_version: Mapped[str] = mapped_column(
        String(32), default="metabolism_v3", nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="app", nullable=False)


class AdminAppEdit(Base):
    __tablename__ = "admin_app_edits"

    id: Mapped[uuid.UUID] = uuid_pk()
    admin_username: Mapped[str] = mapped_column(String(255), nullable=False)
    target_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    app_code: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContentSource(TimestampMixin, Base):
    __tablename__ = "content_sources"
    __table_args__ = (
        UniqueConstraint("platform", "account_key", name="uq_content_source_account"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    account_key: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContentItem(TimestampMixin, Base):
    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_content_item_external"),
        Index("ix_content_items_published_at", "published_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_sources.id", ondelete="RESTRICT"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="published", nullable=False)
    latest_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_item_versions.id", ondelete="SET NULL", use_alter=True)
    )
    source_tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    ending_text: Mapped[str | None] = mapped_column(Text)
    ending_kind: Mapped[str | None] = mapped_column(String(32))
    cta_text: Mapped[str | None] = mapped_column(Text)
    cta_url: Mapped[str | None] = mapped_column(Text)
    recommendations_status: Mapped[str] = mapped_column(
        String(32), default="review", nullable=False
    )
    review_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )


class ContentItemVersion(Base):
    __tablename__ = "content_item_versions"
    __table_args__ = (
        UniqueConstraint("item_id", "version_no", name="uq_content_item_version_no"),
        UniqueConstraint("item_id", "content_hash", name="uq_content_item_version_hash"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    blocks: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContentMedia(Base):
    __tablename__ = "content_media"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "position", "source_url", name="uq_content_media_position_url"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_item_versions.id", ondelete="CASCADE"), index=True
    )
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    preview_url: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ContentLink(Base):
    __tablename__ = "content_links"

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_item_versions.id", ondelete="CASCADE"), index=True
    )
    visible_text: Mapped[str | None] = mapped_column(Text)
    wrapped_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    link_type: Mapped[str] = mapped_column(String(32), default="other", nullable=False)
    is_cta: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ignored_for_generation: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class ContentMetricSnapshot(Base):
    __tablename__ = "content_metric_snapshots"
    __table_args__ = (
        Index("ix_content_metric_item_captured", "item_id", "captured_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), index=True
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metric_source: Mapped[str] = mapped_column(String(32), nullable=False)
    views: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[int | None] = mapped_column(Integer)
    pluses: Mapped[int | None] = mapped_column(Integer)
    minuses: Mapped[int | None] = mapped_column(Integer)
    saves: Mapped[int | None] = mapped_column(Integer)
    comments_reported: Mapped[int | None] = mapped_column(Integer)
    emotions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class ContentImportRun(Base):
    __tablename__ = "content_import_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_sources.id", ondelete="SET NULL"), index=True
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
