"""Channel entry settings in the existing link catalog and document versions."""
from __future__ import annotations

import hashlib
import re
import json
import secrets
import string
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.managed_documents import active_document, document_hash, publish_document
from app.models import ManagedDocumentVersion, MessengerAccount, TelegramTrackingEvent, TelegramTrackingLink, TelegramTrackingLinkAlias, TelegramTrackingSession

DOCUMENT_TYPE = "channel-entry-link"
MAX_DESTINATION = "https://max.ru/id230409966750_biz"
DEFAULT_DESTINATION = "https://t.me/Fitness_Talks/260"
SOURCES = {"site": "website", "ig": "instagram", "yt": "youtube", "th": "threads",
           "pk": "pikabu", "dz": "dzen", "vk": "vk", "tt": "tiktok", "ya": "yandex"}
PLATFORMS = {"website": "Сайт", "instagram": "Instagram", "youtube": "YouTube",
             "threads": "Threads", "pikabu": "Пикабу", "dzen": "Дзен",
             "vk": "ВКонтакте", "tiktok": "TikTok", "yandex": "Яндекс.Директ", "other": "Другое"}


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=255)
    platform: str
    placement: str = Field(default="Профиль", min_length=1, max_length=255)
    destination: str = Field(default=DEFAULT_DESTINATION, max_length=2048)
    request_write_access: bool = True
    max_destination: str = Field(default=MAX_DESTINATION, max_length=2048)

    @field_validator("name", "placement")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Введите название")
        return value

    @field_validator("platform")
    @classmethod
    def platform_known(cls, value):
        if value not in PLATFORMS:
            raise ValueError("Выберите площадку")
        return value

    @field_validator("destination")
    @classmethod
    def own_channel(cls, value):
        value = value.strip()
        parsed = urlsplit(value)
        parts = parsed.path.strip("/").split("/")
        if (parsed.scheme != "https" or parsed.netloc != "t.me" or parsed.query or parsed.fragment
                or parts[0].casefold() != "fitness_talks" or len(parts) != 2 or not re.fullmatch(r"[1-9][0-9]*", parts[1])):
            raise ValueError("Нужна ссылка на пост канала https://t.me/Fitness_Talks/номер")
        return "https://t.me/Fitness_Talks/" + parts[1]

    @field_validator("max_destination")
    @classmethod
    def own_max_channel(cls, value):
        parsed = urlsplit(value.strip())
        parts = parsed.path.strip("/").split("/")
        if (parsed.scheme != "https" or parsed.netloc != "max.ru" or parsed.query or parsed.fragment
                or parts[0] != "id230409966750_biz" or len(parts) > 2
                or (len(parts) == 2 and not re.fullmatch(r"[1-9][0-9]*", parts[1]))):
            raise ValueError("Нужна ссылка на собственный канал MAX или его пост")
        return "https://max.ru/" + "/".join(parts)


class LinkUpdateIn(LinkIn):
    expected_version: int = Field(ge=1)


def link_payload(db: Session, link: TelegramTrackingLink, username: str) -> dict:
    doc = active_document(db, DOCUMENT_TYPE, link.id)
    if not doc:
        raise HTTPException(404, "Настройки ссылки не найдены")
    return {"id": link.id, "code": link.token, "version": doc.version_no,
            **{"max_destination": MAX_DESTINATION, **doc.payload},
            "max_url": f"https://max.ru/{get_settings().max_bot_username.lstrip('@')}?startapp={link.token}", "url": f"https://t.me/{username.lstrip('@')}/channel?startapp={link.token}"}


def create_link(db: Session, body: LinkIn, admin: str, *, code: str | None = None) -> TelegramTrackingLink:
    code = code or ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    if (db.scalar(select(TelegramTrackingLink.id).where(TelegramTrackingLink.token == code))
            or db.scalar(select(TelegramTrackingLinkAlias.id).where(TelegramTrackingLinkAlias.token == code))):
        raise HTTPException(409, "Код ссылки уже занят")
    row = TelegramTrackingLink(id=str(uuid.uuid4()), token=code, name=body.name, platform=body.platform,
                               placement=body.placement, target_kind="channel_entry", status="active", created_by=admin)
    db.add(row)
    db.add(TelegramTrackingLinkAlias(tracking_link_id=row.id, token=code, alias_kind="channel_entry", created_by=admin))
    payload = body.model_dump()
    db.add(ManagedDocumentVersion(document_type=DOCUMENT_TYPE, document_key=row.id,
        schema_version=1, version_no=1, payload=payload, content_hash=document_hash(payload),
        created_by=admin, is_active=True))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Ссылка уже создана, обновите список") from exc
    return row


def update_link(db: Session, link_id: str, body: LinkUpdateIn, admin: str) -> TelegramTrackingLink:
    row = db.scalar(select(TelegramTrackingLink).where(TelegramTrackingLink.id == link_id,
        TelegramTrackingLink.target_kind == "channel_entry").with_for_update())
    if not row:
        raise HTTPException(404, "Ссылка не найдена")
    payload = body.model_dump(exclude={"expected_version"})
    publish_document(db, document_type=DOCUMENT_TYPE, document_key=row.id, schema_version=1,
        payload=payload, expected_version=body.expected_version, admin=admin, commit=False)
    row.name, row.platform, row.placement = body.name, body.platform, body.placement
    db.commit()
    return row


def resolve_entry(db: Session, code: str) -> tuple[TelegramTrackingLink | None, dict]:
    journey = db.scalar(select(TelegramTrackingSession).where(
        TelegramTrackingSession.start_token_hash == hashlib.sha256(code.encode()).hexdigest()).with_for_update()) if code.startswith("U") else None
    if journey is not None:
        expiry = journey.expires_at.replace(tzinfo=timezone.utc) if journey.expires_at.tzinfo is None else journey.expires_at
        if expiry <= datetime.now(timezone.utc) or journey.consumed_at is not None:
            journey = None
    query = select(TelegramTrackingLink).where(TelegramTrackingLink.target_kind == "channel_entry",
        TelegramTrackingLink.status == "active", TelegramTrackingLink.is_active.is_(True))
    row = db.scalar(query.where(TelegramTrackingLink.id == journey.tracking_link_id)) if journey else db.scalar(select(TelegramTrackingLink).where(TelegramTrackingLink.token == code,
        TelegramTrackingLink.target_kind == "channel_entry", TelegramTrackingLink.status == "active",
        TelegramTrackingLink.is_active.is_(True)))
    if row is None and code in SOURCES:
        try:
            row = create_link(db, LinkIn(name=PLATFORMS[SOURCES[code]], platform=SOURCES[code]),
                              "system-seed", code=code)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            row = db.scalar(select(TelegramTrackingLink).where(TelegramTrackingLink.token == code,
                TelegramTrackingLink.target_kind == "channel_entry", TelegramTrackingLink.status == "active",
                TelegramTrackingLink.is_active.is_(True)))
    doc = active_document(db, DOCUMENT_TYPE, row.id) if row else None
    if not row or not doc:
        return None, {"destination": DEFAULT_DESTINATION, "max_destination": MAX_DESTINATION, "request_write_access": code == "writepreview"}
    # Validate saved settings at the public boundary too; a corrupted document is not a redirect.
    payload = LinkIn.model_validate(doc.payload).model_dump()
    payload["configuration_version"] = doc.version_no
    if journey:
        prepared = db.scalar(select(TelegramTrackingEvent).where(
            TelegramTrackingEvent.deduplication_key == f"link_prepared:{journey.id}"))
        payload["journey_id"] = journey.id
        payload["raw_query"] = dict(journey.raw_query or {})
        payload["session_tag_ids"] = list(journey.resolved_tag_ids or [])
        payload["journey_context"] = dict(prepared.metadata_json or {}) if prepared else {}
    return row, payload


def entry_identity(db: Session, telegram_id: str, messenger: str = "telegram"):
    return db.scalar(select(MessengerAccount).where(MessengerAccount.platform == messenger,
                                                   MessengerAccount.platform_user_id == telegram_id))


def known_bot_contact(db: Session, telegram_id: str, username: str, messenger: str = "telegram") -> bool:
    if inspect(db.connection()).has_table("tg_contacts"):
        return db.scalar(text("SELECT 1 FROM tg_contacts c JOIN tg_bot_instances b ON b.id=c.bot_instance_id "
            "WHERE c.telegram_user_id=:uid AND lower(b.username)=lower(:bot) LIMIT 1"),
            {"uid": telegram_id, "bot": username.lstrip("@")}) is not None
    return db.scalar(select(TelegramTrackingEvent.id).where(TelegramTrackingEvent.telegram_user_id == telegram_id,
        (TelegramTrackingEvent.event_type.like("start_%") | (TelegramTrackingEvent.event_type == "channel_write_allowed"))).limit(1)) is not None


def record_observation(db: Session, *, init_data: str, telegram_id: str, kind: str,
                       granted: bool | None = None, username: str = "Fitness_Talks_bot", messenger: str = "telegram") -> dict:
    code = dict(parse_qsl(init_data)).get("start_param", "")
    visit = hashlib.sha256(((messenger + ":") if messenger != "telegram" else "").encode() + init_data.encode()).hexdigest()
    dedup = f"channel-entry:{visit}:{kind}"
    opening = db.scalar(select(TelegramTrackingEvent).where(
        TelegramTrackingEvent.deduplication_key == f"channel-entry:{visit}:channel_entry_open"))
    if kind != "channel_entry_open" and opening is None:
        raise HTTPException(409, "Сначала откройте приложение")
    if opening is not None:
        snapshot = opening.metadata_json
        config = {"destination": snapshot["destination"], "request_write_access": snapshot["request_write_access"],
                  "platform": snapshot.get("source"), "placement": snapshot.get("placement"),
                  **{key: snapshot[key] for key in ("journey_id", "raw_query", "journey_context", "session_tag_ids", "configuration_version") if key in snapshot}}
        row = db.get(TelegramTrackingLink, opening.tracking_link_id) if opening.tracking_link_id else None
    else:
        row, config = resolve_entry(db, code)
        if messenger == "max":
            config["destination"] = config.get("max_destination", MAX_DESTINATION)
            config["request_write_access"] = False
        if config.get("journey_id"):
            db.get(TelegramTrackingSession, config["journey_id"]).consumed_at = datetime.now(timezone.utc)
    account = entry_identity(db, telegram_id, messenger)
    current = db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.deduplication_key == dedup))
    if current:
        meta = current.metadata_json
        return {"destination": meta["destination"], "source": meta.get("source"), "request_write_access": meta["request_write_access"]}
    if not current:
        metadata = {"messenger": messenger, "visit": visit, "code": row.token if row else (code if code in {"preview", "writepreview"} else None), "source": config.get("platform"),
                    "placement": config.get("placement"), "destination": config["destination"],
                    "request_write_access": config["request_write_access"],
                    "known_contact": known_bot_contact(db, telegram_id, username, messenger),
                    "already_allowed": json.loads(dict(parse_qsl(init_data)).get("user", "{}")).get("allows_write_to_pm")}
        for key in ("journey_id", "raw_query", "journey_context", "session_tag_ids", "configuration_version"):
            if key in config:
                metadata[key] = config[key]
        if kind == "channel_permission_result":
            metadata["client_granted"] = granted
        db.add(TelegramTrackingEvent(tracking_link_id=row.id if row else None,
            user_id=account.user_id if account else None, telegram_user_id=telegram_id,
            event_type=kind, deduplication_key=dedup, metadata_json=metadata))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            saved = db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.deduplication_key == dedup))
            if saved is None:
                raise
            meta = saved.metadata_json
            return {"destination": meta["destination"], "source": meta.get("source"), "request_write_access": meta["request_write_access"]}
    return {"destination": config["destination"], "source": config.get("platform"),
            "request_write_access": config["request_write_access"]}
