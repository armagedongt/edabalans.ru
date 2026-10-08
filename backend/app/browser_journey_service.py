from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.intensive_web_access import access_token_row, checkout_source_context_row
from app.models import MessengerAccount, TelegramTrackingEvent, User

COOKIE_NAME = "edabalans_visitor"
RETENTION = timedelta(days=365)
TRANSFER_TTL = timedelta(minutes=10)
ROOTS = tuple(host.encode("idna").decode() for host in (
    "edabalans.ru", "похудение-это-есть.рф", "похудение.рф",
))
EVENT_TYPES = ("visitor_state", "browser_page", "browser_action", "browser_identified")


def public_host(host: str) -> bool:
    try:
        value = host.encode("idna").decode().lower()
    except UnicodeError:
        return False
    if value.startswith("admin."):
        return False
    return any(value == root or value.endswith("." + root) for root in ROOTS)


def _cipher(secret: str) -> Fernet:
    key = hashlib.sha256(("browser-journey-v1\0" + secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def issue_context(secret: str, browser_id: str, *, transfer: bool = False) -> str:
    payload = {"id": browser_id, "purpose": "transfer" if transfer else "visitor"}
    return _cipher(secret).encrypt(json.dumps(payload).encode()).decode()


def context_id(secret: str, value: str | None, *, transfer: bool = False) -> str | None:
    if not secret or not value or len(value) > 512:
        return None
    try:
        payload = json.loads(_cipher(secret).decrypt(value.encode("ascii"), ttl=int(
            (TRANSFER_TTL if transfer else RETENTION).total_seconds()
        )))
        if not isinstance(payload, dict) or payload.get("purpose") != ("transfer" if transfer else "visitor"):
            return None
        return str(uuid.UUID(payload["id"]))
    except (InvalidToken, ValueError, TypeError, KeyError, UnicodeEncodeError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def state_row(db: Session, browser_id: str, *, lock: bool = False) -> TelegramTrackingEvent | None:
    for _ in range(8):
        query = select(TelegramTrackingEvent).where(
            TelegramTrackingEvent.deduplication_key == f"visitor:{browser_id}",
            TelegramTrackingEvent.event_type == "visitor_state",
            TelegramTrackingEvent.occurred_at >= _now() - RETENTION,
        )
        row = db.scalar(query.with_for_update() if lock else query)
        if row is None:
            return None
        target = (row.metadata_json or {}).get("merged_into")
        if not target:
            return row
        browser_id = str(target)
    return None


def _new_state(db: Session) -> TelegramTrackingEvent:
    browser_id = str(uuid.uuid4())
    row = TelegramTrackingEvent(id=str(uuid.uuid4()), event_type="visitor_state",
                                deduplication_key=f"visitor:{browser_id}",
                                metadata_json={"browser_id": browser_id}, occurred_at=_now())
    db.add(row)
    db.flush()
    return row


def _backfill(db: Session, browser_id: str, user_id: uuid.UUID) -> None:
    db.execute(update(TelegramTrackingEvent).where(
        TelegramTrackingEvent.event_type.in_(("browser_page", "browser_action")),
        TelegramTrackingEvent.metadata_json["browser_id"].as_string() == browser_id,
        TelegramTrackingEvent.user_id.is_(None),
        TelegramTrackingEvent.occurred_at >= _now() - RETENTION,
    ).values(user_id=user_id))


def resolve_browser(db: Session, secret: str, context: str | None, transfer: str | None = None) -> TelegramTrackingEvent:
    current_id = context_id(secret, context)
    transfer_id = context_id(secret, transfer, transfer=True)
    current = state_row(db, current_id, lock=True) if current_id else None
    arriving = state_row(db, transfer_id, lock=True) if transfer_id else None
    row = arriving or current or _new_state(db)
    if arriving and current and arriving.id != current.id and current.user_id is None:
        metadata = dict(current.metadata_json)
        metadata["merged_into"] = row.metadata_json["browser_id"]
        current.metadata_json = metadata
        history = db.scalars(select(TelegramTrackingEvent).where(
            TelegramTrackingEvent.event_type.in_(("browser_page", "browser_action")),
            TelegramTrackingEvent.metadata_json["browser_id"].as_string() == metadata["browser_id"],
            TelegramTrackingEvent.user_id.is_(None),
        ))
        for event in history:
            event.metadata_json = {**event.metadata_json, "browser_id": row.metadata_json["browser_id"]}
            event.user_id = row.user_id
    row.occurred_at = _now()
    return row


def bind_personal(db: Session, row: TelegramTrackingEvent, secret: str, *,
                  token: str | None = None, source_context: str | None = None) -> bool:
    personal = access_token_row(db, token) if token else checkout_source_context_row(db, secret, source_context)
    user = db.get(User, personal.user_id) if personal else None
    if not user or user.status != "active" or user.merged_into_user_id:
        return False
    row.user_id = user.id
    metadata = dict(row.metadata_json)
    metadata.update(platform=personal.platform, personal_token_id=str(personal.id))
    metadata.pop("source_bot", None)
    starts = db.scalars(select(TelegramTrackingEvent).where(
        TelegramTrackingEvent.user_id == user.id,
        TelegramTrackingEvent.event_type.in_(("start_first", "start_repeat", "start_maintenance")),
    ).order_by(TelegramTrackingEvent.occurred_at.desc()).limit(20)).all()
    for start in starts:
        details = start.metadata_json or {}
        start_platform = "max" if details.get("messenger") == "max" else "telegram"
        if details.get("source_bot") and start_platform == personal.platform and not metadata.get("source_bot"):
            metadata["source_bot"] = details["source_bot"]
        previous_id = context_id(secret, details.get("browser_context"))
        previous = state_row(db, previous_id, lock=True) if previous_id else None
        if previous and previous.user_id is None and previous.id != row.id:
            old_id = previous.metadata_json["browser_id"]
            previous.metadata_json = {**previous.metadata_json, "merged_into": metadata["browser_id"]}
            for event in db.scalars(select(TelegramTrackingEvent).where(
                TelegramTrackingEvent.event_type.in_(("browser_page", "browser_action")),
                TelegramTrackingEvent.metadata_json["browser_id"].as_string() == old_id,
                TelegramTrackingEvent.user_id.is_(None),
                TelegramTrackingEvent.occurred_at >= _now() - RETENTION,
            )):
                event.metadata_json = {**event.metadata_json, "browser_id": metadata["browser_id"]}
                event.user_id = user.id
    row.metadata_json = metadata
    browser_id = metadata["browser_id"]
    _backfill(db, browser_id, user.id)
    aliases = db.scalars(select(TelegramTrackingEvent).where(
        TelegramTrackingEvent.event_type == "visitor_state",
        TelegramTrackingEvent.metadata_json["merged_into"].as_string() == browser_id,
        TelegramTrackingEvent.user_id.is_(None),
    )).all()
    for alias in aliases:
        _backfill(db, alias.metadata_json["browser_id"], user.id)
    row.occurred_at = _now()
    return True


def clean_page_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not public_host(parsed.hostname or ""):
            return None
        if parsed.username or parsed.password or parsed.path.startswith(("/admin", "/crm", "/api", "/auth", "/health", "/ready", "/weather")):
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path[:512], "", ""))
    except (ValueError, UnicodeError):
        return None


def record_browser_event(db: Session, row: TelegramTrackingEvent, event_type: str,
                         page_url: str, *, attribution: dict | None = None, action: str | None = None) -> None:
    page = clean_page_url(page_url)
    if not page:
        return
    values = {key: str(value)[:255] for key, value in (attribution or {}).items()
              if key in {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "yclid", "alias"}}
    db.add(TelegramTrackingEvent(id=str(uuid.uuid4()), user_id=row.user_id, event_type=event_type,
        metadata_json={"browser_id": row.metadata_json["browser_id"], "page_url": page,
                       "raw_query": values, "action": (action or "")[:80]}, occurred_at=_now()))


def contact_snapshot(db: Session, row: TelegramTrackingEvent | None) -> dict | None:
    if row is None or row.user_id is None:
        return None
    user = db.get(User, row.user_id)
    if not user or user.status != "active" or user.merged_into_user_id:
        return None
    metadata = row.metadata_json or {}
    return {"browser_id": metadata.get("browser_id"), "user_id": str(row.user_id),
            "platform": metadata.get("platform"), "source_bot": metadata.get("source_bot"),
            "binding": "personal_bot_link"}


def snapshot_for_context(db: Session, secret: str, context: str | None) -> dict | None:
    browser_id = context_id(secret, context)
    return contact_snapshot(db, state_row(db, browser_id)) if browser_id else None


def attach_personal_browser(db: Session, request, response, secret: str, token: str) -> None:
    if not secret:
        return
    row = resolve_browser(db, secret, request.cookies.get(COOKIE_NAME),
                          request.query_params.get("visitor_transfer"))
    if not bind_personal(db, row, secret, token=token):
        return
    db.commit()
    browser_id = row.metadata_json["browser_id"]
    host = request.url.hostname or ""
    domain = next((root for root in ROOTS if host == root or host.endswith("." + root)), None)
    response.set_cookie(COOKIE_NAME, issue_context(secret, browser_id), domain=domain,
                        max_age=int(RETENTION.total_seconds()), secure=True, samesite="lax", path="/")
    target = response.headers.get("location")
    if target and target.startswith("https://"):
        response.headers["location"] = with_transfer(target, issue_context(secret, browser_id, transfer=True))


def observed_accounts(db: Session, snapshot: dict | None) -> list[MessengerAccount]:
    try:
        user_id = uuid.UUID(snapshot["user_id"])
    except (KeyError, ValueError, TypeError):
        return []
    return list(db.scalars(select(MessengerAccount).where(
        MessengerAccount.user_id == user_id, MessengerAccount.platform_user_id.is_not(None),
        MessengerAccount.is_deliverable.is_(True),
    ).order_by(MessengerAccount.platform)))


def with_transfer(target: str, transfer: str) -> str:
    parsed = urlsplit(target)
    if parsed.scheme != "https" or not public_host(parsed.hostname or ""):
        return target
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != "visitor_transfer"]
    query.append(("visitor_transfer", transfer))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def purge_browser_history(db: Session, *, now: datetime | None = None) -> int:
    result = db.execute(delete(TelegramTrackingEvent).where(
        TelegramTrackingEvent.event_type.in_(EVENT_TYPES),
        TelegramTrackingEvent.occurred_at < (now or _now()) - RETENTION,
    ))
    return result.rowcount


async def browser_history_worker() -> None:
    import asyncio
    import logging
    from app.database import SessionLocal

    def clean():
        with SessionLocal() as db:
            purge_browser_history(db)
            db.commit()

    while True:
        try:
            await asyncio.to_thread(clean)
        except Exception:
            logging.getLogger(__name__).exception("Browser history cleanup failed")
        await asyncio.sleep(3600)
