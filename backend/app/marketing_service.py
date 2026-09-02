from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
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
DAY_ONE_EVENTS = {"intensive_day_1_open", "day_1_open"}
SITE_HOME_EVENTS = {"site_home_open", "intensive_home_open"}
EVENT_LIMIT = 100_000
ROW_LIMIT = 2_000
DEFAULT_SOURCES = ["Яндекс", "Пикабу", "Telegram", "MAX", "Не определён"]

EVENT_LABELS = {
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
    user_query: str | None = None,
) -> dict[str, Any]:
    start, end = _period_bounds(date_from, date_to)
    links = {item.id: item for item in db.scalars(select(TelegramTrackingLink)).all()}
    users = list(db.scalars(select(User)).all())
    accounts = list(db.scalars(select(MessengerAccount)).all())
    canonical_user_map = _canonical_user_map(users)

    telegram_user_map: dict[str, str] = {}
    for account in accounts:
        if account.platform == "telegram" and account.platform_user_id:
            user_id = str(account.user_id)
            telegram_user_map[str(account.platform_user_id)] = canonical_user_map.get(user_id, user_id)

    click_rows = db.execute(
        select(TelegramTrackingEvent.tracking_link_id, func.count(TelegramTrackingEvent.id))
        .where(
            TelegramTrackingEvent.occurred_at >= start,
            TelegramTrackingEvent.occurred_at < end,
            TelegramTrackingEvent.event_type == "web_click",
        )
        .group_by(TelegramTrackingEvent.tracking_link_id)
    ).all()
    telegram_events = list(
        db.scalars(
            select(TelegramTrackingEvent)
            .where(
                TelegramTrackingEvent.occurred_at >= start,
                TelegramTrackingEvent.occurred_at < end,
                TelegramTrackingEvent.event_type != "web_click",
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
    events_truncated = len(telegram_events) > EVENT_LIMIT or len(max_events) > EVENT_LIMIT
    telegram_events = telegram_events[:EVENT_LIMIT]
    max_events = max_events[:EVENT_LIMIT]
    for event in telegram_events:
        if event.telegram_user_id and event.user_id:
            user_id = str(event.user_id)
            telegram_user_map[str(event.telegram_user_id)] = canonical_user_map.get(user_id, user_id)
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
        query = _raw_query(event)
        candidate = {
            "source": _normalize_source((link.platform if link else None) or query.get("utm_source")),
            "placement": (link.placement if link else None) or query.get("utm_medium") or "—",
            "campaign": (link.campaign if link else None) or query.get("utm_campaign") or "Без кампании",
            "link_name": (link.name if link else None) or getattr(event, "source_raw", None) or "Без tracking-ссылки",
        }
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

    events_by_identity: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        events_by_identity[_identity(event, telegram_user_map, canonical_user_map)].append(event)

    starts: dict[str, Any] = {}
    for event in events:
        if event.event_type not in START_EVENTS:
            continue
        identity = _identity(event, telegram_user_map, canonical_user_map)
        starts.setdefault(identity, event)

    rows: list[dict[str, Any]] = []
    for identity, start_event in starts.items():
        identity_events = [
            event
            for event in events_by_identity[identity]
            if event.occurred_at and start_event.occurred_at and event.occurred_at >= start_event.occurred_at
        ]
        tracking_link_id = getattr(start_event, "tracking_link_id", None)
        link = links.get(tracking_link_id or "")
        query = _raw_query(start_event)
        attribution = {
            "source": _normalize_source((link.platform if link else None) or query.get("utm_source")),
            "placement": (link.placement if link else None) or query.get("utm_medium") or "—",
            "campaign": (link.campaign if link else None) or query.get("utm_campaign") or "Без кампании",
            "link_name": (link.name if link else None) or getattr(start_event, "source_raw", None) or "Без tracking-ссылки",
        }
        if identity in first_touch:
            attribution = first_touch[identity]

        user_id = identity.removeprefix("user:") if identity.startswith("user:") else None
        user = user_by_id.get(user_id or "")
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
                **attribution,
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

    all_sources = {
        *DEFAULT_SOURCES,
        *(_normalize_source(link.platform) for link in links.values()),
        *(row["source"] for row in rows),
    }
    all_campaigns = {link.campaign or "Без кампании" for link in links.values()} | {
        row["campaign"] for row in rows
    }

    normalized_source_filter = _normalize_source(source_filter) if source_filter else None
    campaign_needle = (campaign_filter or "").strip().casefold()
    user_needle = (user_query or "").strip().casefold()
    filtered_rows = []
    for row in rows:
        if normalized_source_filter and row["source"] != normalized_source_filter:
            continue
        if campaign_needle and campaign_needle not in row["campaign"].casefold():
            continue
        user_haystack = " ".join(
            [row["display_name"], row.get("user_id") or "", *row["usernames"]]
        ).casefold()
        if user_needle and user_needle not in user_haystack:
            continue
        filtered_rows.append(row)
    filtered_rows.sort(key=lambda row: row["start"]["at"] or "", reverse=True)
    rows_truncated = len(filtered_rows) > ROW_LIMIT
    visible_rows = filtered_rows[:ROW_LIMIT]

    click_count = 0
    for tracking_link_id, count in click_rows:
        link = links.get(tracking_link_id or "")
        click_source = _normalize_source(link.platform if link else None)
        click_campaign = (link.campaign if link else None) or "Без кампании"
        if normalized_source_filter and click_source != normalized_source_filter:
            continue
        if campaign_needle and campaign_needle not in click_campaign.casefold():
            continue
        click_count += int(count)

    started_count = len(filtered_rows)
    collection = {
        "day_one": settings.marketing_day_one_events_enabled
        or any(bool(row["day_one"]) for row in rows),
        "site_home": settings.marketing_site_home_events_enabled
        or any(bool(row["site_home"]) for row in rows),
        "later_days": settings.marketing_later_day_events_enabled
        or any(bool(row["later_days"]) for row in rows),
    }
    metric_specs = [
        ("web_click", "Переходы", click_count, True),
        ("bot_start", "Запустили бота", started_count, True),
        (
            "check_before_day_one",
            "Проверка подписки до дня 1",
            sum(bool(row["check_before_day_one"]) for row in filtered_rows),
            True,
        ),
        (
            "day_one",
            "Открыли день 1",
            sum(bool(row["day_one"]) for row in filtered_rows),
            collection["day_one"],
        ),
        (
            "subscribed",
            "Подписка подтверждена",
            sum(bool(row["subscription"]) for row in filtered_rows),
            True,
        ),
        (
            "check_after_day_one",
            "Проверка подписки после дня 1",
            sum(bool(row["check_after_day_one"]) for row in filtered_rows),
            True,
        ),
        (
            "site_home",
            "Открыли главную",
            sum(bool(row["site_home"]) for row in filtered_rows),
            collection["site_home"],
        ),
        (
            "later_days",
            "Открыли дни 2+",
            sum(bool(row["later_days"]) for row in filtered_rows),
            collection["later_days"],
        ),
    ]
    analytics = [
        {
            "code": code,
            "label": label,
            "count": count,
            "conversion_from_start": None
            if code in {"web_click", "bot_start"}
            else _percent(count, started_count),
            "collection": "collecting" if enabled else "not_connected",
        }
        for code, label, count, enabled in metric_specs
    ]

    return {
        "period": {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
            "timezone": "Europe/Moscow",
        },
        "filters": {
            "sources": sorted(all_sources, key=lambda value: (value == "Не определён", value)),
            "campaigns": sorted(all_campaigns),
            "selected": {
                "source": normalized_source_filter or "",
                "campaign": campaign_filter or "",
                "user": user_query or "",
            },
        },
        "rows": visible_rows,
        "analytics": analytics,
        "collection": collection,
        "totals": {
            "rows": len(visible_rows),
            "matching_rows": len(filtered_rows),
            "all_rows_before_filters": len(rows),
            "truncated": rows_truncated,
            "events_truncated": events_truncated or history_truncated,
            "clicks_ignore_user_filter": bool(user_needle),
        },
    }
