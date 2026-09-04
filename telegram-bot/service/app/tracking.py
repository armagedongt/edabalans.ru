from __future__ import annotations

import hashlib
import secrets
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Contact,
    CrmAttributionEvent,
    CrmMessengerAccount,
    CrmTag,
    CrmUser,
    CrmUserTag,
    TrackingEvent,
    TrackingLink,
    TrackingLinkAlias,
    TrackingLinkTag,
    TrackingSession,
    UtmTagRule,
)


CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
UTM_PREFIX = "utm_"
YANDEX_CLICK_ID = "yclid"


def tracking_query_params(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    query: dict[str, str] = {}
    for name, value in pairs:
        normalized_name = name.casefold()
        if normalized_name.startswith(UTM_PREFIX):
            query[name] = value
        elif normalized_name == YANDEX_CLICK_ID:
            query[YANDEX_CLICK_ID] = value
    return query


def normalize_value(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def tag_code(name: str) -> str:
    digest = hashlib.sha1(normalize_value(name).encode()).hexdigest()[:12]
    return f"manual_{digest}"


def generate_alias_token(session: Session, target_kind: str) -> str:
    prefix = "C" if target_kind == "channel_invite" else "B"
    for _ in range(24):
        token = prefix + "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
        if not session.scalar(select(TrackingLinkAlias.id).where(TrackingLinkAlias.token == token)):
            return token
    raise RuntimeError("Не удалось создать уникальный короткий код")


def resolve_alias(session: Session, token: str) -> tuple[TrackingLinkAlias | None, bool]:
    alias = session.scalar(select(TrackingLinkAlias).where(TrackingLinkAlias.token == token))
    if alias:
        return alias, False
    if len(token) == 6 and token.endswith("V"):
        alias = session.scalar(select(TrackingLinkAlias).where(TrackingLinkAlias.token == token[:-1]))
        if alias and alias.alias_kind == "short":
            return alias, True
    return None, False


def active_link(session: Session, alias: TrackingLinkAlias | None) -> TrackingLink | None:
    if not alias or alias.status != "active":
        return None
    link = session.get(TrackingLink, alias.tracking_link_id)
    return link if link and link.status == "active" and link.is_active else None


def exact_utm_matches(session: Session, query: dict[str, str]) -> list[str]:
    matched: list[str] = []
    for key, value in query.items():
        rule = session.scalar(
            select(UtmTagRule).where(
                UtmTagRule.parameter_name == key.casefold(),
                UtmTagRule.normalized_value == normalize_value(value),
                UtmTagRule.status == "active",
            )
        )
        if rule and rule.tag_id not in matched:
            matched.append(rule.tag_id)
    return matched


def create_tracking_session(
    session: Session, link: TrackingLink, alias: TrackingLinkAlias, query: dict[str, str]
) -> str:
    public_token = "U" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")
    session.add(
        TrackingSession(
            start_token_hash=hashlib.sha256(public_token.encode()).hexdigest(),
            tracking_link_id=link.id,
            alias_id=alias.id,
            raw_query=query,
            resolved_tag_ids=exact_utm_matches(session, query),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    return public_token


def resolve_start_payload(
    session: Session, payload: str | None
) -> tuple[TrackingLink | None, TrackingLinkAlias | None, list[str], dict[str, str], str]:
    if not payload:
        return None, None, [], {}, "empty"
    if payload.startswith("U"):
        row = session.scalar(
            select(TrackingSession).where(
                TrackingSession.start_token_hash == hashlib.sha256(payload.encode()).hexdigest()
            ).with_for_update()
        )
        expires_at = row.expires_at.replace(tzinfo=UTC) if row and row.expires_at.tzinfo is None else (row.expires_at if row else None)
        if not row or row.consumed_at or expires_at < datetime.now(UTC):
            return None, None, [], {}, "expired_session"
        row.consumed_at = datetime.now(UTC)
        return (
            session.get(TrackingLink, row.tracking_link_id),
            session.get(TrackingLinkAlias, row.alias_id),
            list(row.resolved_tag_ids or []),
            dict(row.raw_query or {}),
            "known",
        )
    alias, warning_suffix = resolve_alias(session, payload)
    if warning_suffix:
        return None, None, [], {}, "unknown"
    link = active_link(session, alias)
    return (link, alias, [], {}, "known") if link else (None, None, [], {}, "unknown")


def resolve_pending_channel_touch(
    session: Session, telegram_user_id: str
) -> tuple[TrackingLink | None, TrackingLinkAlias | None, dict[str, str]]:
    event = session.scalar(
        select(TrackingEvent)
        .where(
            TrackingEvent.telegram_user_id == telegram_user_id,
            TrackingEvent.event_type.in_(["channel_join", "channel_join_request"]),
            TrackingEvent.processed_at.is_(None),
        )
        .order_by(TrackingEvent.occurred_at.desc())
    )
    if not event:
        return None, None, {}
    event.processed_at = datetime.now(UTC)
    return session.get(TrackingLink, event.tracking_link_id), session.get(TrackingLinkAlias, event.alias_id), dict((event.metadata_json or {}).get("raw_query") or {})


def ensure_crm_identity(session: Session, contact: Contact, telegram: dict) -> CrmMessengerAccount:
    telegram_id = str(telegram["id"])
    account = session.scalar(
        select(CrmMessengerAccount).where(
            CrmMessengerAccount.platform == "telegram",
            CrmMessengerAccount.platform_user_id == telegram_id,
        )
    )
    now = datetime.now(UTC)
    if not account:
        user = session.get(CrmUser, contact.user_id) if contact.user_id else None
        if not user:
            user = CrmUser(
                display_name=" ".join(filter(None, [telegram.get("first_name"), telegram.get("last_name")])) or None,
                status="active",
                data_origin="native",
                first_seen_at=now,
            )
            session.add(user)
            session.flush()
        account = CrmMessengerAccount(
            user_id=user.id,
            platform="telegram",
            platform_user_id=telegram_id,
            username=telegram.get("username"),
            first_name=telegram.get("first_name"),
            first_seen_at=now,
            last_seen_at=now,
            linked_at=now,
            source="telegram_bot",
        )
        session.add(account)
        session.flush()
    else:
        account.username = telegram.get("username")
        account.first_name = telegram.get("first_name")
        account.last_seen_at = now
    contact.user_id = account.user_id
    return account


def canonical_tag(session: Session, tag_id: str) -> CrmTag | None:
    tag = session.get(CrmTag, tag_id)
    seen: set[str] = set()
    while tag and tag.merged_into_tag_id and tag.id not in seen:
        seen.add(tag.id)
        tag = session.get(CrmTag, tag.merged_into_tag_id)
    return tag if tag and tag.status == "active" else None


def link_tag_ids(session: Session, link_id: str) -> list[str]:
    return list(session.scalars(select(TrackingLinkTag.tag_id).where(TrackingLinkTag.tracking_link_id == link_id)))


def assign_first_touch(
    session: Session,
    account: CrmMessengerAccount,
    contact: Contact,
    link: TrackingLink | None,
    alias: TrackingLinkAlias | None,
    session_tag_ids: list[str],
    raw_query: dict[str, str],
    payload_status: str,
    *,
    mark_scenario_seen: bool = True,
) -> tuple[bool, list[str]]:
    now = datetime.now(UTC)
    is_first = account.main_scenario_seen_at is None
    prior_bot_start = session.scalar(select(TrackingEvent.id).where(
        TrackingEvent.user_id == account.user_id,
        TrackingEvent.event_type.in_((
            "start_first", "start_repeat", "start_maintenance",
            "start_unknown", "start_expired_session",
        )),
    ))
    is_first_bot_visit = prior_bot_start is None
    if is_first and mark_scenario_seen:
        account.main_scenario_seen_at = now
    assigned: list[str] = []
    event_type = "start_first" if is_first else "start_repeat"
    if not mark_scenario_seen:
        event_type = "start_maintenance"
    elif payload_status == "unknown":
        event_type = "start_unknown"
    elif payload_status == "expired_session":
        event_type = "start_expired_session"
    session.add(
        TrackingEvent(
            tracking_link_id=link.id if link else None,
            alias_id=alias.id if alias else None,
            contact_id=contact.id,
            user_id=account.user_id,
            telegram_user_id=contact.telegram_user_id,
            event_type=event_type,
            metadata_json={
                "payload_status": payload_status,
                "raw_query": raw_query,
                "is_first_bot_visit": is_first_bot_visit,
            },
        )
    )
    if not is_first or not link or contact.first_source_token:
        return is_first, assigned

    candidate_ids = [*link_tag_ids(session, link.id), *session_tag_ids]
    for tag_id in dict.fromkeys(candidate_ids):
        tag = canonical_tag(session, tag_id)
        if not tag:
            continue
        exists = session.scalar(
            select(CrmUserTag.id).where(CrmUserTag.user_id == account.user_id, CrmUserTag.tag_id == tag.id)
        )
        if not exists:
            session.add(CrmUserTag(user_id=account.user_id, tag_id=tag.id, source="telegram_first_touch"))
        assigned.append(tag.id)
    session.add(
        CrmAttributionEvent(
            user_id=account.user_id,
            event_type="telegram_first_touch",
            source_raw=link.name,
            utm_source=raw_query.get("utm_source"),
            utm_medium=raw_query.get("utm_medium"),
            utm_campaign=raw_query.get("utm_campaign"),
            utm_content=raw_query.get("utm_content"),
            utm_term=raw_query.get("utm_term"),
            ref_code=alias.token if alias else None,
            occurred_at=now,
        )
    )
    contact.first_source_token = contact.first_source_token or (alias.token if alias else None)
    return is_first, assigned


def parse_utm_url(url: str) -> dict:
    parsed = urlparse(url)
    parameters = []
    for name, value in parse_qsl(parsed.query, keep_blank_values=True):
        if not name.casefold().startswith(UTM_PREFIX):
            continue
        parameters.append({"name": name.casefold(), "raw_value": value, "normalized_value": normalize_value(value)})
    return {"url": url, "parameters": parameters}


def unresolved_utm_groups(session: Session) -> list[dict]:
    events = session.scalars(select(TrackingEvent).where(TrackingEvent.event_type == "web_click")).all()
    groups: dict[tuple, dict] = {}
    for event in events:
        raw = (event.metadata_json or {}).get("raw_query") or {}
        values = {str(k).casefold(): str(v) for k, v in raw.items() if str(k).casefold().startswith(UTM_PREFIX)}
        if not values:
            continue
        unresolved = []
        for key, value in values.items():
            known = session.scalar(select(UtmTagRule.id).where(UtmTagRule.parameter_name == key, UtmTagRule.normalized_value == normalize_value(value), UtmTagRule.status == "active"))
            if not known:
                unresolved.append((key, value))
        if not unresolved:
            continue
        key = tuple(sorted((name, normalize_value(value)) for name, value in values.items()))
        group = groups.setdefault(key, {"parameters": values, "count": 0, "first_seen_at": event.occurred_at, "last_seen_at": event.occurred_at})
        group["count"] += 1
        group["first_seen_at"] = min(group["first_seen_at"], event.occurred_at)
        group["last_seen_at"] = max(group["last_seen_at"], event.occurred_at)
    return sorted(groups.values(), key=lambda item: item["last_seen_at"], reverse=True)
