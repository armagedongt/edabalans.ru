from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    AttributionEvent,
    MessengerAccount,
    TelegramTrackingEvent,
    TelegramTrackingLink,
    User,
)


MOSCOW_TZ = ZoneInfo("Europe/Moscow")
START_EVENTS = {
    "start_first",
    "start_repeat",
    "start_maintenance",
    "start_unknown",
    "start_expired_session",
    "max_first_touch",
    "max_start_maintenance",
    "max_start_unknown",
}
MAX_START_EVENTS = {"max_first_touch", "max_start_maintenance", "max_start_unknown"}
FIRST_START_EVENTS = {"start_first", "max_first_touch"}
DAY_ONE_EVENTS = {"intensive_day_1_open", "day_1_open"}
SITE_HOME_EVENTS = {"site_home_open", "intensive_home_open"}
EVENT_LIMIT = 100_000
ROW_LIMIT = 2_000
DEFAULT_SOURCES = ["Яндекс", "Пикабу", "Telegram", "MAX", "Не определён"]

EVENT_LABELS = {
    "landing_button_click": "Нажал кнопку на посадке",
    "landing_qr_scan": "Отсканировал QR-код",
    "link_prepared": "Ссылка подготовлена",
    "start_first": "Первый старт бота",
    "start_repeat": "Повторный старт бота",
    "start_maintenance": "Старт в техническом режиме",
    "start_unknown": "Старт без известной ссылки",
    "start_expired_session": "Старт по истёкшей ссылке",
    "max_first_touch": "Первый старт MAX",
    "max_start_maintenance": "Старт MAX в техническом режиме",
    "max_start_unknown": "Старт MAX без известной ссылки",
    "subscription_check": "Проверка подписки",
    "channel_join": "Вступил в канал",
    "channel_join_request": "Отправил заявку в канал",
    "maintenance_contact": "Действие в техническом режиме",
    "messenger_link_confirmed": "Связал мессенджер",
    "start_routing_error": "Ошибка стартового маршрута",
    "subscription_fail_open": "Проверка подписки недоступна",
    "site_home_open": "Открыл главную",
    "intensive_home_open": "Открыл главную",
}
LANDING_ENTRY_EVENTS = {"landing_button_click", "landing_qr_scan"}


def _telegram_contact_statuses(db: Session) -> list[tuple[str, str]]:
    """Read the messaging-owned table without registering it in backend metadata."""

    if not inspect(db.get_bind()).has_table("tg_contacts"):
        return []
    return [
        (str(row.user_id), str(row.status))
        for row in db.execute(
            text("SELECT user_id, status FROM tg_contacts WHERE user_id IS NOT NULL")
        )
    ]


def _period_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    start = datetime.combine(date_from, time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    return start, end


def _normalize_source(value: str | None) -> str:
    source = (value or "").strip()
    folded = source.casefold()
    if not folded or "не определ" in folded:
        return "Не определён"
    if "яндекс" in folded or "yandex" in folded:
        return "Яндекс"
    if "пикабу" in folded or "pikabu" in folded:
        return "Пикабу"
    if folded == "max" or folded.startswith("max "):
        return "MAX"
    if "telegram" in folded or "телеграм" in folded:
        return "Telegram"
    return source


def _day_number(event: Any) -> int | None:
    if event.event_type == "intensive_day_open":
        metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        try:
            return int(metadata.get("day"))
        except (TypeError, ValueError):
            return None
    prefix, suffix = "intensive_day_", "_open"
    if event.event_type.startswith(prefix) and event.event_type.endswith(suffix):
        try:
            return int(event.event_type[len(prefix) : -len(suffix)])
        except ValueError:
            return None
    return None


def _canonical_user_map(users: list[User]) -> dict[str, str]:
    merges = {
        str(user.id): str(user.merged_into_user_id) if user.merged_into_user_id else None
        for user in users
    }

    def canonical(user_id: str) -> str:
        seen: set[str] = set()
        current = user_id
        while merges.get(current) and current not in seen:
            seen.add(current)
            current = merges[current] or current
        return current

    return {user_id: canonical(user_id) for user_id in merges}


def _identity(
    event: Any,
    telegram_user_map: dict[str, str],
    canonical_user_map: dict[str, str],
) -> str:
    if event.user_id:
        user_id = str(event.user_id)
        return f"user:{canonical_user_map.get(user_id, user_id)}"
    telegram_user_id = getattr(event, "telegram_user_id", None)
    if telegram_user_id:
        mapped = telegram_user_map.get(str(telegram_user_id))
        if mapped:
            return f"user:{canonical_user_map.get(mapped, mapped)}"
        return f"telegram:{telegram_user_id}"
    return f"event:{event.id}"


def _raw_query(event: Any) -> dict[str, str]:
    if isinstance(event, AttributionEvent):
        return {
            key: str(value)
            for key, value in {
                "utm_source": event.utm_source,
                "utm_medium": event.utm_medium,
                "utm_campaign": event.utm_campaign,
            }.items()
            if value
        }
    metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
    raw = metadata.get("raw_query")
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _journey_context(event: Any) -> dict[str, str]:
    metadata = event.metadata_json if isinstance(event, TelegramTrackingEvent) and isinstance(event.metadata_json, dict) else {}
    return {
        key: str(metadata[key])
        for key in ("journey_id", "entry", "messenger")
        if metadata.get(key)
    }


def _attribution_values(event: Any, link: TelegramTrackingLink | None) -> dict[str, str]:
    query = _raw_query(event)
    return {
        "source": _normalize_source(query.get("utm_source") or (link.platform if link else None)),
        "placement": query.get("utm_medium") or (link.placement if link else None) or "—",
        "campaign": query.get("utm_campaign") or (link.campaign if link else None) or "Без кампании",
        "creative": query.get("utm_content") or "—",
        "term": query.get("utm_term") or "—",
        "link_name": (link.name if link else None) or getattr(event, "source_raw", None) or "Без tracking-ссылки",
    }


def _is_legacy_real_click(event: TelegramTrackingEvent) -> bool:
    if event.event_type != "web_click":
        return False
    metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
    return metadata.get("entry") != "public_start_link_api"


def _is_confirmed_bot_start(event: Any) -> bool:
    if event.event_type not in START_EVENTS:
        return False
    if not isinstance(event, TelegramTrackingEvent):
        return True
    metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
    if metadata.get("messenger") != "max":
        return True
    return metadata.get("max_delivery_status") == "sent"


def _event_detail(event: Any) -> str | None:
    if not isinstance(event, TelegramTrackingEvent) or not isinstance(event.metadata_json, dict):
        return None
    metadata = event.metadata_json
    if event.event_type == "subscription_check":
        outcomes = {
            "already_subscribed": "уже подписан",
            "subscribed_after_prompt": "подписался после предложения",
            "not_subscribed_initially": "не подписан",
            "not_subscribed_after_prompt": "не подписался после предложения",
            "not_subscribed_at_check": "не подписан",
            "not_checked_placeholder": "проверка ещё не выполнялась",
        }
        return outcomes.get(str(metadata.get("outcome"))) or str(metadata.get("stage") or "проверено")
    return None


def _event_label(event: Any) -> str:
    day = _day_number(event)
    if day:
        return f"Открыл день {day}"
    return EVENT_LABELS.get(event.event_type, event.event_type.replace("_", " "))


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _percent(value: int, base: int) -> float | None:
    return round(value * 100 / base, 1) if base else None


def marketing_dashboard(
    db: Session,
    settings: Settings,
    *,
    date_from: date,
    date_to: date,
    source_filter: str | None = None,
    campaign_filter: str | None = None,
    creative_filter: str | None = None,
    user_query: str | None = None,
) -> dict[str, Any]:
    start, end = _period_bounds(date_from, date_to)
    links = {item.id: item for item in db.scalars(select(TelegramTrackingLink)).all()}
    users = list(db.scalars(select(User)).all())
    accounts = list(db.scalars(select(MessengerAccount)).all())
    contacts = _telegram_contact_statuses(db)
    canonical_user_map = _canonical_user_map(users)

    telegram_user_map: dict[str, str] = {}
    for account in accounts:
        if account.platform == "telegram" and account.platform_user_id:
            user_id = str(account.user_id)
            telegram_user_map[str(account.platform_user_id)] = canonical_user_map.get(user_id, user_id)

    raw_entry_events = list(
        db.scalars(
            select(TelegramTrackingEvent)
            .where(
                TelegramTrackingEvent.occurred_at >= start,
                TelegramTrackingEvent.occurred_at < end,
                TelegramTrackingEvent.event_type.in_([*LANDING_ENTRY_EVENTS, "web_click"]),
            )
            .order_by(TelegramTrackingEvent.occurred_at.asc())
            .limit(EVENT_LIMIT + 1)
        )
    )
    entry_events_truncated = len(raw_entry_events) > EVENT_LIMIT
    entry_events = [
        event
        for event in raw_entry_events[:EVENT_LIMIT]
        if event.event_type in LANDING_ENTRY_EVENTS or _is_legacy_real_click(event)
    ]
    telegram_events = list(
        db.scalars(
            select(TelegramTrackingEvent)
            .where(
                TelegramTrackingEvent.occurred_at >= start,
                TelegramTrackingEvent.occurred_at < end,
                TelegramTrackingEvent.event_type.not_in(
                    ["web_click", "link_prepared", *LANDING_ENTRY_EVENTS]
                ),
            )
            .order_by(TelegramTrackingEvent.occurred_at.desc())
            .limit(EVENT_LIMIT + 1)
        )
    )
    max_events = list(
        db.scalars(
            select(AttributionEvent)
            .where(
                AttributionEvent.occurred_at >= start,
                AttributionEvent.occurred_at < end,
                AttributionEvent.event_type.in_(MAX_START_EVENTS),
            )
            .order_by(AttributionEvent.occurred_at.desc())
            .limit(EVENT_LIMIT + 1)
        )
    )
    events_truncated = (
        entry_events_truncated
        or len(telegram_events) > EVENT_LIMIT
        or len(max_events) > EVENT_LIMIT
    )
    telegram_events = telegram_events[:EVENT_LIMIT]
    max_events = max_events[:EVENT_LIMIT]
    for event in telegram_events:
        if event.telegram_user_id and event.user_id:
            user_id = str(event.user_id)
            telegram_user_map[str(event.telegram_user_id)] = canonical_user_map.get(user_id, user_id)
    max_tracking_identities = {
        _identity(event, telegram_user_map, canonical_user_map)
        for event in telegram_events
        if isinstance(event.metadata_json, dict)
        and event.metadata_json.get("messenger") == "max"
        and event.event_type in START_EVENTS
    }
    max_events = [
        event
        for event in max_events
        if _identity(event, telegram_user_map, canonical_user_map) not in max_tracking_identities
    ]
    events: list[Any] = [*telegram_events, *max_events]
    events.sort(key=lambda event: event.occurred_at or datetime.min.replace(tzinfo=timezone.utc))

    attribution_start = datetime(2025, 12, 1, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    telegram_history = list(
        db.scalars(
            select(TelegramTrackingEvent)
            .where(
                TelegramTrackingEvent.occurred_at >= attribution_start,
                TelegramTrackingEvent.occurred_at < end,
                TelegramTrackingEvent.event_type.in_(START_EVENTS),
            )
            .order_by(TelegramTrackingEvent.occurred_at.asc())
            .limit(EVENT_LIMIT + 1)
        )
    )
    max_history = list(
        db.scalars(
            select(AttributionEvent)
            .where(
                AttributionEvent.occurred_at >= attribution_start,
                AttributionEvent.occurred_at < end,
                AttributionEvent.event_type.in_(MAX_START_EVENTS),
            )
            .order_by(AttributionEvent.occurred_at.asc())
            .limit(EVENT_LIMIT + 1)
        )
    )
    history_truncated = len(telegram_history) > EVENT_LIMIT or len(max_history) > EVENT_LIMIT
    telegram_history = telegram_history[:EVENT_LIMIT]
    max_history = max_history[:EVENT_LIMIT]
    for event in telegram_history:
        if event.telegram_user_id and event.user_id:
            user_id = str(event.user_id)
            telegram_user_map[str(event.telegram_user_id)] = canonical_user_map.get(user_id, user_id)

    history: list[Any] = [*telegram_history, *max_history]
    history.sort(key=lambda event: event.occurred_at or datetime.min.replace(tzinfo=timezone.utc))
    first_touch: dict[str, dict[str, str]] = {}
    for event in history:
        identity = _identity(event, telegram_user_map, canonical_user_map)
        tracking_link_id = getattr(event, "tracking_link_id", None)
        link = links.get(tracking_link_id or "")
        candidate = _attribution_values(event, link)
        existing = first_touch.get(identity)
        if existing is None or (
            existing["source"] == "Не определён" and candidate["source"] != "Не определён"
        ):
            first_touch[identity] = candidate

    user_by_id = {str(user.id): user for user in users}
    accounts_by_user: dict[str, list[MessengerAccount]] = defaultdict(list)
    for account in accounts:
        user_id = str(account.user_id)
        accounts_by_user[canonical_user_map.get(user_id, user_id)].append(account)
    contact_status_by_user: dict[str, str] = {}
    for user_id, status in contacts:
        canonical_id = canonical_user_map.get(user_id, user_id)
        current = contact_status_by_user.get(canonical_id)
        if current != "blocked" or status == "blocked":
            contact_status_by_user[canonical_id] = status

    events_by_identity: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        events_by_identity[_identity(event, telegram_user_map, canonical_user_map)].append(event)

    starts: dict[str, Any] = {}
    for event in events:
        if not _is_confirmed_bot_start(event):
            continue
        identity = _identity(event, telegram_user_map, canonical_user_map)
        starts.setdefault(identity, event)

    entry_by_journey: dict[str, TelegramTrackingEvent] = {}
    for event in entry_events:
        journey_id = _journey_context(event).get("journey_id")
        if journey_id:
            entry_by_journey.setdefault(journey_id, event)

    started_journeys: dict[str, Any] = {}
    for event in events:
        if not _is_confirmed_bot_start(event):
            continue
        journey_id = _journey_context(event).get("journey_id")
        if journey_id:
            started_journeys.setdefault(journey_id, event)

    rows: list[dict[str, Any]] = []
    for identity, start_event in starts.items():
        identity_events = [
            event
            for event in events_by_identity[identity]
            if event.occurred_at and start_event.occurred_at and event.occurred_at >= start_event.occurred_at
        ]
        tracking_link_id = getattr(start_event, "tracking_link_id", None)
        link = links.get(tracking_link_id or "")
        attribution = _attribution_values(start_event, link)
        user_id = identity.removeprefix("user:") if identity.startswith("user:") else None
        user = user_by_id.get(user_id or "")
        journey = _journey_context(start_event)
        journey_id = journey.get("journey_id")
        landing_event = entry_by_journey.get(journey_id or "")
        landing_context = _journey_context(landing_event) if landing_event else journey
        if landing_event:
            attribution = _attribution_values(
                landing_event, links.get(landing_event.tracking_link_id or "")
            )
        elif identity in first_touch:
            attribution = first_touch[identity]
        user_accounts = accounts_by_user.get(user_id or "", [])
        preferred_account = next((account for account in user_accounts if account.platform == "telegram"), None)
        preferred_account = preferred_account or next(iter(user_accounts), None)
        display_name = (
            (user.display_name if user else None)
            or (preferred_account.first_name if preferred_account else None)
            or (f"@{preferred_account.username}" if preferred_account and preferred_account.username else None)
            or "Пользователь без имени"
        )
        usernames = [f"@{account.username}" for account in user_accounts if account.username]

        day_one = [event for event in identity_events if event.event_type in DAY_ONE_EVENTS or _day_number(event) == 1]
        first_day_one_at = day_one[0].occurred_at if day_one else None
        checks_before: list[Any] = []
        checks_after: list[Any] = []
        for event in identity_events:
            if event.event_type != "subscription_check" or not isinstance(event.metadata_json, dict):
                continue
            stage = str(event.metadata_json.get("stage") or "")
            is_later_stage = stage.startswith("after_day") or stage.startswith("after_mid")
            if stage in {"before_day1", "after_prompt"}:
                checks_before.append(event)
            elif is_later_stage or (first_day_one_at is not None and event.occurred_at >= first_day_one_at):
                checks_after.append(event)
            else:
                checks_before.append(event)
        site_home = [event for event in identity_events if event.event_type in SITE_HOME_EVENTS]
        later_days = [event for event in identity_events if (_day_number(event) or 0) > 1]
        subscribed_events = [
            event
            for event in identity_events
            if (
                event.event_type == "subscription_check"
                and isinstance(event.metadata_json, dict)
                and event.metadata_json.get("subscribed") is True
            )
            or event.event_type == "channel_join"
        ]
        main_event_types = START_EVENTS | DAY_ONE_EVENTS | SITE_HOME_EVENTS | {
            "subscription_check",
            "channel_join",
            "intensive_day_open",
        }
        other_actions = [
            {"at": _iso(event.occurred_at), "label": _event_label(event), "detail": _event_detail(event)}
            for event in identity_events
            if event.event_type not in main_event_types and _day_number(event) is None
        ]
        last_event = identity_events[-1] if identity_events else start_event
        later_day_numbers = [day for day in (_day_number(event) for event in later_days) if day]
        rows.append(
            {
                "user_id": user_id,
                "display_name": display_name,
                "usernames": usernames,
                "status": contact_status_by_user.get(user_id or "")
                or (user.status if user else "unknown"),
                "is_new_lead": start_event.event_type in FIRST_START_EVENTS,
                **attribution,
                "journey_id": journey_id,
                "messenger": landing_context.get("messenger") or (
                    "max" if start_event.event_type.startswith("max_") else "telegram"
                ),
                "landing_entry": {
                    "at": _iso(landing_event.occurred_at),
                    "label": _event_label(landing_event),
                    "method": landing_context.get("entry")
                    or ("qr" if landing_event and landing_event.event_type == "landing_qr_scan" else "button"),
                    "messenger": landing_context.get("messenger"),
                }
                if landing_event
                else None,
                "start": {"at": _iso(start_event.occurred_at), "label": _event_label(start_event)},
                "check_before_day_one": [
                    {"at": _iso(event.occurred_at), "detail": _event_detail(event)}
                    for event in checks_before
                ],
                "day_one": {"at": _iso(day_one[0].occurred_at)} if day_one else None,
                "subscription": {
                    "at": _iso(subscribed_events[0].occurred_at),
                    "detail": _event_detail(subscribed_events[0]) or _event_label(subscribed_events[0]),
                }
                if subscribed_events
                else None,
                "check_after_day_one": [
                    {"at": _iso(event.occurred_at), "detail": _event_detail(event)}
                    for event in checks_after
                ],
                "site_home": {"at": _iso(site_home[0].occurred_at)} if site_home else None,
                "later_days": {
                    "at": _iso(later_days[0].occurred_at),
                    "max_day": max(later_day_numbers) if later_day_numbers else None,
                }
                if later_days
                else None,
                "other_actions": other_actions,
                "last_action": {
                    "at": _iso(last_event.occurred_at),
                    "label": _event_label(last_event),
                    "detail": _event_detail(last_event),
                },
            }
        )

    for journey_id, landing_event in entry_by_journey.items():
        if journey_id in started_journeys:
            continue
        attribution = _attribution_values(
            landing_event, links.get(landing_event.tracking_link_id or "")
        )
        landing_context = _journey_context(landing_event)
        rows.append(
            {
                "user_id": None,
                "display_name": "Не запустил бота",
                "usernames": [],
                "status": "lost_before_start",
                "is_new_lead": False,
                **attribution,
                "journey_id": journey_id,
                "messenger": landing_context.get("messenger") or "—",
                "landing_entry": {
                    "at": _iso(landing_event.occurred_at),
                    "label": _event_label(landing_event),
                    "method": landing_context.get("entry")
                    or ("qr" if landing_event.event_type == "landing_qr_scan" else "button"),
                    "messenger": landing_context.get("messenger"),
                },
                "start": None,
                "check_before_day_one": [],
                "day_one": None,
                "subscription": None,
                "check_after_day_one": [],
                "site_home": None,
                "later_days": None,
                "other_actions": [],
                "last_action": {
                    "at": _iso(landing_event.occurred_at),
                    "label": _event_label(landing_event),
                    "detail": None,
                },
            }
        )

    all_sources = {
        *DEFAULT_SOURCES,
        *(_normalize_source(link.platform) for link in links.values()),
        *(row["source"] for row in rows),
    }
    all_campaigns = {link.campaign or "Без кампании" for link in links.values()} | {
        row["campaign"] for row in rows
    }
    all_creatives = {row["creative"] for row in rows if row["creative"] != "—"}

    normalized_source_filter = _normalize_source(source_filter) if source_filter else None
    campaign_needle = (campaign_filter or "").strip().casefold()
    creative_needle = (creative_filter or "").strip().casefold()
    user_needle = (user_query or "").strip().casefold()
    filtered_rows = []
    for row in rows:
        if normalized_source_filter and row["source"] != normalized_source_filter:
            continue
        if campaign_needle and campaign_needle not in row["campaign"].casefold():
            continue
        if creative_needle and creative_needle not in row["creative"].casefold():
            continue
        user_haystack = " ".join(
            [row["display_name"], row.get("user_id") or "", *row["usernames"]]
        ).casefold()
        if user_needle and user_needle not in user_haystack:
            continue
        filtered_rows.append(row)
    filtered_rows.sort(key=lambda row: row["last_action"]["at"] or "", reverse=True)
    rows_truncated = len(filtered_rows) > ROW_LIMIT
    visible_rows = filtered_rows[:ROW_LIMIT]

    def event_matches_filters(event: TelegramTrackingEvent) -> bool:
        values = _attribution_values(event, links.get(event.tracking_link_id or ""))
        return not (
            (normalized_source_filter and values["source"] != normalized_source_filter)
            or (campaign_needle and campaign_needle not in values["campaign"].casefold())
            or (creative_needle and creative_needle not in values["creative"].casefold())
        )

    filtered_entries = [event for event in entry_events if event_matches_filters(event)]
    if user_needle:
        user_journeys = {
            row["journey_id"] for row in filtered_rows if row.get("journey_id")
        }
        filtered_entries = [
            event
            for event in filtered_entries
            if _journey_context(event).get("journey_id") in user_journeys
        ]
    button_count = sum(event.event_type == "landing_button_click" for event in filtered_entries)
    qr_count = sum(event.event_type == "landing_qr_scan" for event in filtered_entries)
    legacy_click_count = sum(event.event_type == "web_click" for event in filtered_entries)
    entry_count = button_count + qr_count + legacy_click_count
    started_rows = [row for row in filtered_rows if row["start"]]
    started_count = len(started_rows)
    new_lead_count = sum(row["is_new_lead"] for row in started_rows)
    collection = {
        "day_one": settings.marketing_day_one_events_enabled
        or any(bool(row["day_one"]) for row in started_rows),
        "site_home": settings.marketing_site_home_events_enabled
        or any(bool(row["site_home"]) for row in started_rows),
        "later_days": settings.marketing_later_day_events_enabled
        or any(bool(row["later_days"]) for row in started_rows),
    }
    metric_specs = [
        ("web_click", "Перешли с посадки в мессенджер", entry_count, True),
        ("landing_button_click", "Нажали кнопку", button_count, True),
        ("landing_qr_scan", "Отсканировали QR-код", qr_count, True),
        ("bot_start", "Запустили бота", started_count, True),
        ("new_lead", "Новые лиды", new_lead_count, True),
        (
            "check_before_day_one",
            "Проверка подписки до дня 1",
            sum(bool(row["check_before_day_one"]) for row in started_rows),
            True,
        ),
        (
            "day_one",
            "Открыли день 1",
            sum(bool(row["day_one"]) for row in started_rows),
            collection["day_one"],
        ),
        (
            "subscribed",
            "Подписка подтверждена",
            sum(bool(row["subscription"]) for row in started_rows),
            True,
        ),
        (
            "check_after_day_one",
            "Проверка подписки после дня 1",
            sum(bool(row["check_after_day_one"]) for row in started_rows),
            True,
        ),
        (
            "site_home",
            "Открыли главную",
            sum(bool(row["site_home"]) for row in started_rows),
            collection["site_home"],
        ),
        (
            "later_days",
            "Открыли дни 2+",
            sum(bool(row["later_days"]) for row in started_rows),
            collection["later_days"],
        ),
    ]
    analytics = []
    previous_count: int | None = None
    linear_codes = {"web_click", "bot_start", "day_one", "subscribed", "site_home", "later_days"}
    for code, label, count, enabled in metric_specs:
        is_linear = code in linear_codes
        analytics.append(
            {
                "code": code,
                "label": label,
                "count": count,
                "conversion_from_previous": _percent(count, previous_count)
                if is_linear and previous_count is not None
                else None,
                "lost_from_previous": max(previous_count - count, 0)
                if is_linear and previous_count is not None
                else None,
                "conversion_from_start": None
                if code in {"web_click", "landing_button_click", "landing_qr_scan", "bot_start", "new_lead"}
                else _percent(count, started_count),
                "collection": "collecting" if enabled else "not_connected",
            }
        )
        if is_linear:
            previous_count = count

    breakdown: dict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    for event in filtered_entries:
        values = _attribution_values(event, links.get(event.tracking_link_id or ""))
        context = _journey_context(event)
        journey_id = context.get("journey_id") or f"legacy:{event.id}"
        method = context.get("entry") or (
            "qr" if event.event_type == "landing_qr_scan" else "button"
        )
        messenger = context.get("messenger") or "не определён"
        breakdown[(values["source"], values["campaign"], values["creative"], messenger, method)].add(journey_id)
    entry_breakdown = []
    for key, journey_ids in breakdown.items():
        matched = sum(journey_id in started_journeys for journey_id in journey_ids)
        entry_breakdown.append(
            {
                "source": key[0],
                "campaign": key[1],
                "creative": key[2],
                "messenger": key[3],
                "entry": key[4],
                "entries": len(journey_ids),
                "starts": matched,
                "lost": len(journey_ids) - matched,
                "conversion": _percent(matched, len(journey_ids)),
            }
        )
    entry_breakdown.sort(key=lambda item: (-item["entries"], item["campaign"], item["creative"]))

    return {
        "period": {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
            "timezone": "Europe/Moscow",
        },
        "filters": {
            "sources": sorted(all_sources, key=lambda value: (value == "Не определён", value)),
            "campaigns": sorted(all_campaigns),
            "creatives": sorted(all_creatives),
            "selected": {
                "source": normalized_source_filter or "",
                "campaign": campaign_filter or "",
                "creative": creative_filter or "",
                "user": user_query or "",
            },
        },
        "rows": visible_rows,
        "analytics": analytics,
        "entry_breakdown": entry_breakdown,
        "collection": collection,
        "totals": {
            "rows": len(visible_rows),
            "matching_rows": len(filtered_rows),
            "all_rows_before_filters": len(rows),
            "truncated": rows_truncated,
            "events_truncated": events_truncated or history_truncated,
            "clicks_ignore_user_filter": bool(
                user_needle and any(event.event_type == "web_click" for event in entry_events)
            ),
        },
    }
