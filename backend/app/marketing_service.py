from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AttributionEvent, TelegramTrackingEvent, TelegramTrackingLink, User


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
DAY_ONE_EVENTS = {"intensive_day_1_open", "day_1_open"}
SITE_HOME_EVENTS = {"site_home_open", "intensive_home_open"}
MAX_START_EVENTS = {"max_first_touch", "max_start_maintenance", "max_start_unknown"}
EVENT_LIMIT = 50_000
BREAKDOWN_LIMIT = 200


def _period_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    start = datetime.combine(date_from, time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    return start, end


def _identity(
    event: Any,
    telegram_user_map: dict[str, str] | None = None,
    canonical_user_map: dict[str, str] | None = None,
) -> str:
    if event.user_id:
        user_id = str(event.user_id)
        return f"user:{(canonical_user_map or {}).get(user_id, user_id)}"
    telegram_user_id = getattr(event, "telegram_user_id", None)
    if telegram_user_id:
        mapped_user_id = (telegram_user_map or {}).get(telegram_user_id)
        if mapped_user_id:
            return f"user:{(canonical_user_map or {}).get(mapped_user_id, mapped_user_id)}"
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


def _day_number(event: Any) -> int | None:
    if event.event_type == "intensive_day_open":
        value = (event.metadata_json or {}).get("day")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    prefix, suffix = "intensive_day_", "_open"
    if event.event_type.startswith(prefix) and event.event_type.endswith(suffix):
        try:
            return int(event.event_type[len(prefix) : -len(suffix)])
        except ValueError:
            return None
    return None


def _first_times(
    events: list[Any], telegram_user_map: dict[str, str], canonical_user_map: dict[str, str]
) -> dict[str, datetime]:
    result: dict[str, datetime] = {}
    for event in events:
        identity = _identity(event, telegram_user_map, canonical_user_map)
        occurred_at = event.occurred_at
        if occurred_at is not None and (identity not in result or occurred_at < result[identity]):
            result[identity] = occurred_at
    return result


def _after(
    previous: dict[str, datetime],
    events: list[Any],
    telegram_user_map: dict[str, str],
    canonical_user_map: dict[str, str],
) -> dict[str, datetime]:
    result: dict[str, datetime] = {}
    for event in events:
        identity = _identity(event, telegram_user_map, canonical_user_map)
        occurred_at = event.occurred_at
        if occurred_at is None or identity not in previous or occurred_at < previous[identity]:
            continue
        if identity not in result or occurred_at < result[identity]:
            result[identity] = occurred_at
    return result


def _percent(value: int, base: int) -> float | None:
    if not base:
        return None
    return round(value * 100 / base, 1)


def marketing_dashboard(
    db: Session,
    settings: Settings,
    *,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    start, end = _period_bounds(date_from, date_to)
    links = {item.id: item for item in db.scalars(select(TelegramTrackingLink)).all()}
    click_rows = db.execute(
        select(TelegramTrackingEvent.tracking_link_id, func.count(TelegramTrackingEvent.id))
        .where(
            TelegramTrackingEvent.occurred_at >= start,
            TelegramTrackingEvent.occurred_at < end,
            TelegramTrackingEvent.event_type == "web_click",
        )
        .group_by(TelegramTrackingEvent.tracking_link_id)
    ).all()
    click_count = sum(int(count) for _, count in click_rows)
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
    period_truncated = len(telegram_events) > EVENT_LIMIT or len(max_events) > EVENT_LIMIT
    telegram_events = telegram_events[:EVENT_LIMIT]
    max_events = max_events[:EVENT_LIMIT]
    events: list[Any] = [*telegram_events, *max_events]
    events.sort(key=lambda event: event.occurred_at)
    attribution_start = datetime(2025, 12, 1, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    telegram_start_history = list(
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
    max_start_history = list(
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
    history_truncated = len(telegram_start_history) > EVENT_LIMIT or len(max_start_history) > EVENT_LIMIT
    start_history: list[Any] = [
        *telegram_start_history[:EVENT_LIMIT],
        *max_start_history[:EVENT_LIMIT],
    ]
    start_history.sort(key=lambda event: event.occurred_at)
    user_merges = {
        str(user_id): str(merged_into_user_id) if merged_into_user_id else None
        for user_id, merged_into_user_id in db.execute(select(User.id, User.merged_into_user_id)).all()
    }

    def canonical_user(user_id: str) -> str:
        seen: set[str] = set()
        current = user_id
        while user_merges.get(current) and current not in seen:
            seen.add(current)
            current = user_merges[current] or current
        return current

    canonical_user_map = {user_id: canonical_user(user_id) for user_id in user_merges}
    telegram_user_map = {
        event.telegram_user_id: canonical_user(str(event.user_id))
        for event in [*telegram_start_history, *telegram_events]
        if event.telegram_user_id and event.user_id
    }

    starts = [event for event in events if event.event_type in START_EVENTS]
    subscribed = [
        event
        for event in events
        if isinstance(event, TelegramTrackingEvent)
        and event.event_type == "subscription_check"
        and isinstance(event.metadata_json, dict)
        and event.metadata_json.get("subscribed") is True
    ]
    day_one = [event for event in events if event.event_type in DAY_ONE_EVENTS or _day_number(event) == 1]
    site_home = [event for event in events if event.event_type in SITE_HOME_EVENTS]
    later_days = [event for event in events if (_day_number(event) or 0) > 1]

    start_times = _first_times(starts, telegram_user_map, canonical_user_map)
    day_one_times = _after(start_times, day_one, telegram_user_map, canonical_user_map)
    # A stage may be bypassed only while its producer is explicitly not connected.
    # Once enabled, an honest zero must stop the following sequential stages.
    subscription_base = day_one_times if settings.marketing_day_one_events_enabled else start_times
    subscription_times = _after(subscription_base, subscribed, telegram_user_map, canonical_user_map)
    home_base = subscription_times
    site_home_times = _after(home_base, site_home, telegram_user_map, canonical_user_map)
    later_base = site_home_times if settings.marketing_site_home_events_enabled else home_base
    later_day_times = _after(later_base, later_days, telegram_user_map, canonical_user_map)

    stage_rows = [
        {"code": "web_click", "label": "Переходы", "count": click_count, "status": "collecting", "conversion": None},
        {"code": "bot_start", "label": "Запустили бота", "count": len(start_times), "status": "collecting", "conversion": _percent(len(start_times), click_count)},
        {"code": "intensive_day_1_open", "label": "Открыли день 1", "count": len(day_one_times), "status": "collecting" if settings.marketing_day_one_events_enabled else "pending", "conversion": _percent(len(day_one_times), len(start_times))},
        {"code": "channel_subscribed", "label": "Подписались", "count": len(subscription_times), "status": "collecting", "conversion": _percent(len(subscription_times), len(subscription_base))},
        {"code": "site_home_open", "label": "Открыли главную", "count": len(site_home_times), "status": "collecting" if settings.marketing_site_home_events_enabled else "pending", "conversion": _percent(len(site_home_times), len(home_base))},
        {"code": "intensive_later_open", "label": "Открыли следующие дни", "count": len(later_day_times), "status": "collecting" if settings.marketing_later_day_events_enabled else "pending", "conversion": _percent(len(later_day_times), len(later_base))},
    ]

    attribution_by_identity: dict[str, tuple[str, str, str, str]] = {}
    for event in start_history:
        tracking_link_id = getattr(event, "tracking_link_id", None)
        link = links.get(tracking_link_id or "")
        query = _raw_query(event)
        attribution_by_identity.setdefault(
            _identity(event, telegram_user_map, canonical_user_map),
            (
                (link.platform if link else None) or query.get("utm_source") or "Не определён",
                (link.placement if link else None) or query.get("utm_medium") or "—",
                (link.campaign if link else None) or query.get("utm_campaign") or "Без кампании",
                link.name if link else (getattr(event, "source_raw", None) or "Без tracking-ссылки"),
            ),
        )

    breakdown: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"clicks": 0, "starts": set(), "day_one": set(), "subscribed": set(), "later_days": set()}
    )
    for tracking_link_id, count in click_rows:
        link = links.get(tracking_link_id or "")
        key = (
            link.platform if link else "Не определён",
            link.placement if link else "—",
            link.campaign if link and link.campaign else "Без кампании",
            link.name if link else "Без tracking-ссылки",
        )
        breakdown[key]["clicks"] += int(count)
    for event in events:
        tracking_link_id = getattr(event, "tracking_link_id", None)
        link = links.get(tracking_link_id or "")
        query = _raw_query(event)
        identity = _identity(event, telegram_user_map, canonical_user_map)
        inherited = attribution_by_identity.get(identity)
        source = (inherited[0] if inherited else None) or (link.platform if link else None) or query.get("utm_source") or "Не определён"
        placement = (inherited[1] if inherited else None) or (link.placement if link else None) or query.get("utm_medium") or "—"
        campaign = (inherited[2] if inherited else None) or (link.campaign if link else None) or query.get("utm_campaign") or "Без кампании"
        link_name = (inherited[3] if inherited else None) or (link.name if link else None) or "Без tracking-ссылки"
        row = breakdown[(source, placement, campaign, link_name)]
        if event.event_type in START_EVENTS:
            row["starts"].add(identity)
        if identity in day_one_times and (event.event_type in DAY_ONE_EVENTS or _day_number(event) == 1):
            row["day_one"].add(identity)
        if identity in subscription_times and event in subscribed:
            row["subscribed"].add(identity)
        if identity in later_day_times and (_day_number(event) or 0) > 1:
            row["later_days"].add(identity)

    rows = []
    for (source, placement, campaign, link_name), values in breakdown.items():
        if not any((values["clicks"], values["starts"], values["day_one"], values["subscribed"], values["later_days"])):
            continue
        rows.append(
            {
                "source": source,
                "placement": placement,
                "campaign": campaign,
                "link_name": link_name,
                "clicks": values["clicks"],
                "bot_starts": len(values["starts"]),
                "day_one_opens": len(values["day_one"]),
                "subscribers": len(values["subscribed"]),
                "later_day_users": len(values["later_days"]),
                "click_to_start": _percent(len(values["starts"]), values["clicks"]),
                "start_to_day_one": _percent(len(values["day_one"]), len(values["starts"])),
            }
        )
    rows.sort(key=lambda item: (item["day_one_opens"], item["bot_starts"], item["clicks"]), reverse=True)
    breakdown_truncated = len(rows) > BREAKDOWN_LIMIT
    rows = rows[:BREAKDOWN_LIMIT]

    days: dict[int, set[str]] = defaultdict(set)
    for event in events:
        day = _day_number(event)
        if day:
            identity = _identity(event, telegram_user_map, canonical_user_map)
            if (day == 1 and identity in day_one_times) or (day > 1 and identity in later_day_times):
                days[day].add(identity)

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat(), "timezone": "Europe/Moscow"},
        "stages": stage_rows,
        "day_opens": [{"day": day, "users": len(identities)} for day, identities in sorted(days.items())],
        "breakdown": rows,
        "data_quality": {
            "truncated": period_truncated or history_truncated or breakdown_truncated,
            "event_limit_per_source": EVENT_LIMIT,
            "breakdown_limit": BREAKDOWN_LIMIT,
            "clicks_are_technical": True,
        },
        "integrations": [
            {
                "code": "yandex_direct",
                "label": "Яндекс Директ",
                "status": "configured" if settings.yandex_direct_token else "waiting_api",
                "detail": "Токен сохранён на сервере" if settings.yandex_direct_token else "Ожидается проверка OAuth-токена и доступа Direct API",
            },
            {
                "code": "yandex_metrika",
                "label": "Яндекс Метрика",
                "status": "configured" if settings.yandex_metrika_counter_id else "not_configured",
                "detail": f"Счётчик {settings.yandex_metrika_counter_id}" if settings.yandex_metrika_counter_id else "Счётчик не указан",
            },
            {"code": "telegram", "label": "Telegram", "status": "collecting", "detail": "Старт и проверка подписки читаются из общей базы"},
            {"code": "max", "label": "MAX", "status": "collecting" if max_events else "ready", "detail": "Старт читается из общей базы; полный сценарий добавим по мере запуска"},
            {"code": "pikabu", "label": "Pikabu и другие источники", "status": "ready", "detail": "Добавляются через tracking-ссылки и UTM без новой базы"},
        ],
        "missing_events": [
            {"code": "intensive_day_1_open", "label": "Открытие первого дня", "needed": not settings.marketing_day_one_events_enabled},
            {"code": "site_home_open", "label": "Открытие главной страницы", "needed": not settings.marketing_site_home_events_enabled},
            {"code": "intensive_day_open", "label": "Открытие последующих дней", "needed": not settings.marketing_later_day_events_enabled},
        ],
    }
