from __future__ import annotations

import csv
import io
import json
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.marketing_service import marketing_dashboard
from app.models import CourseEvent, MarketingDailyReport


MOSCOW = ZoneInfo("Europe/Moscow")
DIRECT_REPORT_URL = "https://api.direct.yandex.com/json/v5/reports"
DIRECT_CAMPAIGNS_URL = "https://api.direct.yandex.com/json/v5/campaigns"
CREATIVE_NAMES = {
    1920472171246211821: "Женщина с тортиками",
    1920472171246211822: "Кот с бубликом",
    1920472171246211823: "Кот «Худеть будем?»",
    1920469239931549227: "Поиск · как начать",
    1920469239931549228: "Поиск · без диет и силы воли",
    1920469239931549229: "Поиск · срывы и возврат веса",
}
CAMPAIGN_AD_IDS = {
    "rsya": (1920472171246211821, 1920472171246211822, 1920472171246211823),
    "search": (1920469239931549227, 1920469239931549228, 1920469239931549229),
}


def _campaigns(settings: Settings) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in settings.marketing_report_campaigns.split(","):
        kind, separator, raw_id = item.strip().partition(":")
        if separator and kind in {"search", "rsya"} and raw_id.isdigit():
            result[kind] = int(raw_id)
    if set(result) != {"search", "rsya"}:
        raise RuntimeError("MARKETING_REPORT_CAMPAIGNS must contain search and rsya")
    return result


def _number(value: str | None) -> float:
    if not value or value == "--":
        return 0.0
    return float(value.replace(",", "."))


def _direct_report(settings: Settings, campaign_ids: list[int], start: date, end: date) -> list[dict]:
    if not settings.yandex_direct_token:
        raise RuntimeError("YANDEX_DIRECT_TOKEN is not configured")
    headers = {
        "Authorization": f"Bearer {settings.yandex_direct_token}",
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
        "processingMode": "auto",
        "skipReportHeader": "true",
        "skipReportSummary": "true",
        "skipColumnHeader": "false",
        "returnMoneyInMicros": "false",
    }
    if settings.yandex_direct_client_login:
        headers["Client-Login"] = settings.yandex_direct_client_login
    body = {
        "params": {
            "SelectionCriteria": {
                "Filter": [{"Field": "CampaignId", "Operator": "IN", "Values": [str(value) for value in campaign_ids]}],
                "DateFrom": start.isoformat(),
                "DateTo": end.isoformat(),
            },
            "FieldNames": ["Date", "CampaignId", "AdGroupId", "AdId", "Device", "Impressions", "Clicks", "Sessions", "Cost"],
            "ReportName": f"daily-{'-'.join(map(str, campaign_ids))}-{start}-{end}-{uuid4().hex[:8]}",
            "ReportType": "CUSTOM_REPORT",
            "DateRangeType": "CUSTOM_DATE",
            "Format": "TSV",
            "IncludeVAT": "YES",
            "IncludeDiscount": "YES",
        }
    }
    request_data = json.dumps(body).encode("utf-8")
    for _ in range(7):
        request = urllib.request.Request(DIRECT_REPORT_URL, data=request_data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                text = response.read().decode("utf-8")
                return list(csv.DictReader(io.StringIO(text), delimiter="\t"))
        except urllib.error.HTTPError as error:
            if error.code in {201, 202}:
                time.sleep(min(int(error.headers.get("retryIn", "2")), 10))
                continue
            detail = error.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"Direct report HTTP {error.code}: {detail}") from error
    raise RuntimeError("Direct report generation timeout")


def _weekly_spend_limit(value: Any) -> float | None:
    if isinstance(value, dict):
        if value.get("WeeklySpendLimit") is not None:
            return round(float(value["WeeklySpendLimit"]) / 1_000_000, 2)
        for nested in value.values():
            if (result := _weekly_spend_limit(nested)) is not None:
                return result
    elif isinstance(value, list):
        for nested in value:
            if (result := _weekly_spend_limit(nested)) is not None:
                return result
    return None


def _direct_campaign_budgets(settings: Settings, campaign_ids: list[int]) -> dict[int, float | None]:
    headers = {
        "Authorization": f"Bearer {settings.yandex_direct_token}",
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
    }
    if settings.yandex_direct_client_login:
        headers["Client-Login"] = settings.yandex_direct_client_login
    body = {
        "method": "get",
        "params": {
            "SelectionCriteria": {"Ids": campaign_ids},
            "FieldNames": ["Id", "Name", "Type", "State", "Status"],
            "TextCampaignFieldNames": ["BiddingStrategy"],
        },
    }
    request = urllib.request.Request(
        DIRECT_CAMPAIGNS_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Direct campaigns HTTP {error.code}: {detail}") from error
    result: dict[int, float | None] = {}
    for campaign in payload.get("result", {}).get("Campaigns", []):
        result[int(campaign["Id"])] = _weekly_spend_limit(campaign.get("TextCampaign"))
    return result


def _integer_metric(value: Any) -> int | None:
    if value in (None, "", "--"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _summarize_direct(rows: list[dict]) -> dict:
    total = {"impressions": 0, "clicks": 0, "sessions": 0, "sessions_available": True, "cost_rub": 0.0}
    ads: dict[int, dict] = {}
    devices: dict[str, dict] = defaultdict(
        lambda: {"impressions": 0, "clicks": 0, "sessions": 0, "sessions_available": True, "cost_rub": 0.0}
    )
    for row in rows:
        impressions = int(row.get("Impressions") or 0)
        clicks = int(row.get("Clicks") or 0)
        sessions = _integer_metric(row.get("Sessions"))
        cost = _number(row.get("Cost"))
        ad_id = int(row.get("AdId") or 0)
        device = str(row.get("Device") or "UNKNOWN").lower()
        ad = ads.setdefault(
            ad_id,
            {
                "ad_id": ad_id,
                "name": CREATIVE_NAMES.get(ad_id, str(ad_id)),
                "impressions": 0,
                "clicks": 0,
                "sessions": 0,
                "sessions_available": True,
                "cost_rub": 0.0,
            },
        )
        for target in (total, ad, devices[device]):
            target["impressions"] += impressions
            target["clicks"] += clicks
            if sessions is None:
                target["sessions_available"] = False
            else:
                target["sessions"] += sessions
            target["cost_rub"] += cost
    for target in [total, *ads.values(), *devices.values()]:
        target["cost_rub"] = round(target["cost_rub"], 2)
        target["ctr_percent"] = round(target["clicks"] * 100 / target["impressions"], 2) if target["impressions"] else 0.0
        target["cpc_rub"] = round(target["cost_rub"] / target["clicks"], 2) if target["clicks"] else None
    return {"total": total, "ads": sorted(ads.values(), key=lambda item: item["ad_id"]), "devices": dict(devices)}


def _ensure_known_ads(summary: dict, kind: str) -> dict:
    existing = {int(ad["ad_id"]) for ad in summary["ads"]}
    for ad_id in CAMPAIGN_AD_IDS[kind]:
        if ad_id in existing:
            continue
        summary["ads"].append({
            "ad_id": ad_id,
            "name": CREATIVE_NAMES[ad_id],
            "impressions": 0,
            "clicks": 0,
            "sessions": 0,
            "sessions_available": True,
            "cost_rub": 0.0,
            "ctr_percent": 0.0,
            "cpc_rub": None,
        })
    summary["ads"].sort(key=lambda item: item["ad_id"])
    return summary


def _moscow_date(value: str | None) -> date | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(MOSCOW).date()


def _aware_utc(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _course_depth_snapshot(db: Session, starts: list[dict], cutoff: datetime) -> dict[str, dict[str, int]]:
    """Count unique Start-cohort users reaching day-one reading/video milestones."""

    start_by_user: dict[UUID, datetime] = {}
    for row in starts:
        raw_user_id = row.get("user_id")
        raw_started_at = (row.get("start") or {}).get("at")
        if not raw_user_id or not raw_started_at:
            continue
        try:
            user_id = UUID(str(raw_user_id))
            started_at = _aware_utc(datetime.fromisoformat(raw_started_at))
        except (TypeError, ValueError):
            continue
        start_by_user[user_id] = min(start_by_user.get(user_id, started_at), started_at)

    buckets: dict[str, dict[int, set[UUID]]] = {
        "page": {value: set() for value in (25, 50, 75, 100)},
        "video": {value: set() for value in (25, 50, 75, 100)},
    }
    if not start_by_user:
        return {kind: {str(value): 0 for value in values} for kind, values in buckets.items()}

    events = db.scalars(
        select(CourseEvent).where(
            CourseEvent.user_id.in_(list(start_by_user)),
            CourseEvent.course_code == "intensive",
            CourseEvent.event_type.in_(("page_progress", "video_progress", "video_complete")),
            CourseEvent.occurred_at < _aware_utc(cutoff),
        )
    )
    for event in events:
        if _aware_utc(event.occurred_at) < start_by_user[event.user_id]:
            continue
        details = event.details if isinstance(event.details, dict) else {}
        try:
            day = int(details.get("day") or 0)
        except (TypeError, ValueError):
            continue
        if day != 1:
            continue
        if event.event_type == "video_complete":
            buckets["video"][100].add(event.user_id)
            continue
        try:
            progress = int(details.get("progress_percent") or 0)
        except (TypeError, ValueError):
            continue
        kind = "page" if event.event_type == "page_progress" else "video"
        if progress in buckets[kind]:
            buckets[kind][progress].add(event.user_id)

    return {
        kind: {str(value): len(user_ids) for value, user_ids in values.items()}
        for kind, values in buckets.items()
    }


def _reminder_snapshot(db: Session | None, starts: list[dict], cutoff: datetime) -> dict[str, int | bool]:
    """Count day-one reminders and openings during the next three hours."""

    if db is None or not inspect(db.get_bind()).has_table("tg_step_deliveries"):
        return {"available": False, "sent": 0, "opened_within_3h": 0}

    start_by_user: dict[str, datetime] = {}
    day_one_by_user: dict[str, datetime] = {}
    for row in starts:
        raw_user_id = row.get("user_id")
        raw_started_at = (row.get("start") or {}).get("at")
        if not raw_user_id or not raw_started_at:
            continue
        try:
            started_at = _aware_utc(datetime.fromisoformat(raw_started_at))
        except (TypeError, ValueError):
            continue
        user_id = str(raw_user_id)
        start_by_user[user_id] = min(start_by_user.get(user_id, started_at), started_at)
        raw_day_one_at = (row.get("day_one") or {}).get("at")
        if raw_day_one_at:
            try:
                day_one_by_user[user_id] = _aware_utc(datetime.fromisoformat(raw_day_one_at))
            except (TypeError, ValueError):
                pass

    if not start_by_user:
        return {"available": True, "sent": 0, "opened_within_3h": 0}

    reminder_by_user: dict[str, datetime] = {}
    deliveries = db.execute(
        text(
            """
            SELECT c.user_id, d.sent_at
            FROM tg_step_deliveries d
            JOIN tg_sequence_runs r ON r.id = d.run_id
            JOIN tg_contacts c ON c.id = r.contact_id
            WHERE d.step_key = 'welcome_reminder_day1'
              AND d.status = 'sent'
              AND d.sent_at IS NOT NULL
              AND d.sent_at < :cutoff
              AND c.user_id IS NOT NULL
            """
        ),
        {"cutoff": _aware_utc(cutoff)},
    )
    for raw_user_id, raw_sent_at in deliveries:
        user_id = str(raw_user_id)
        started_at = start_by_user.get(user_id)
        if started_at is None:
            continue
        sent_at = _aware_utc(
            datetime.fromisoformat(raw_sent_at) if isinstance(raw_sent_at, str) else raw_sent_at
        )
        if sent_at < started_at:
            continue
        reminder_by_user[user_id] = min(reminder_by_user.get(user_id, sent_at), sent_at)

    opened_within_3h = 0
    for user_id, sent_at in reminder_by_user.items():
        opened_at = day_one_by_user.get(user_id)
        if opened_at and sent_at <= opened_at < _aware_utc(cutoff) and opened_at <= sent_at + timedelta(hours=3):
            opened_within_3h += 1
    return {
        "available": True,
        "sent": len(reminder_by_user),
        "opened_within_3h": opened_within_3h,
    }


def _internal_snapshot(db: Session, settings: Settings, report_date: date) -> dict:
    dashboard = marketing_dashboard(
        db,
        settings,
        # The calendar-Start cohort may contain a correctly attributed Start
        # between 00:00 and 03:00 whose landing entry happened the previous day.
        date_from=report_date - timedelta(days=1),
        date_to=report_date + timedelta(days=1),
    )
    entry_dashboard = marketing_dashboard(
        db,
        settings,
        date_from=report_date,
        date_to=report_date,
    )
    rows = dashboard["rows"]
    cutoff = datetime.combine(report_date + timedelta(days=1), dt_time(hour=3), tzinfo=MOSCOW)

    def before_cutoff(value: str | None) -> bool:
        if not value:
            return False
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(MOSCOW) < cutoff

    starts = [
        row
        for row in rows
        if row.get("start")
        and row.get("is_new_lead")
        and row.get("source") == "Яндекс"
        and _moscow_date(row["start"]["at"]) == report_date
    ]
    attributed_starts = [
        row
        for row in rows
        if row.get("start")
        and row.get("is_new_lead")
        and row.get("source") == "Яндекс"
        and row.get("landing_entry")
        and _moscow_date(row["landing_entry"]["at"]) == report_date
        and before_cutoff(row["start"].get("at"))
    ]
    entry_breakdown = [
        item
        for item in entry_dashboard.get("entry_breakdown", [])
        if item.get("source") == "Яндекс"
    ]
    entry_count = sum(int(item.get("entries") or 0) for item in entry_breakdown)

    by_creative: dict[str, int] = defaultdict(int)
    by_messenger: dict[str, dict] = defaultdict(lambda: {"entries": 0, "starts": 0})
    by_method: dict[str, dict] = defaultdict(lambda: {"entries": 0, "starts": 0})
    by_device: dict[str, dict] = defaultdict(lambda: {"entries": 0, "starts": 0})
    for row in attributed_starts:
        by_creative[row.get("creative") or "—"] += 1
    for item in entry_breakdown:
        messenger = item.get("messenger") or "не определён"
        method = item.get("entry") or "не определён"
        entries = int(item.get("entries") or 0)
        by_messenger[messenger]["entries"] += entries
        by_method[method]["entries"] += entries
    seen_entry_journeys: set[str] = set()
    for row in entry_dashboard.get("rows", []):
        journey_id = str(row.get("journey_id") or "")
        if (
            row.get("source") != "Яндекс"
            or not row.get("landing_entry")
            or not journey_id
            or journey_id in seen_entry_journeys
        ):
            continue
        seen_entry_journeys.add(journey_id)
        by_device[row.get("device") or "не определён"]["entries"] += 1
    for row in attributed_starts:
        messenger = row.get("messenger") or "не определён"
        method = row.get("entry_method") or "не определён"
        device = row.get("device") or "не определён"
        for bucket, key in ((by_messenger, messenger), (by_method, method), (by_device, device)):
            bucket[key]["starts"] += 1

    def count(cohort: list[dict], predicate) -> int:
        return sum(bool(predicate(row)) for row in cohort)

    def cohort_metrics(cohort: list[dict]) -> dict[str, int]:
        return {
            "starts": len(cohort),
            "personal_or_main_open": count(
                cohort,
                lambda row: (
                    row.get("site_home") and before_cutoff(row["site_home"].get("at"))
                )
                or any(
                    action.get("label") == "Открыл персональную ссылку интенсива"
                    and before_cutoff(action.get("at"))
                    for action in row.get("other_actions", [])
                ),
            ),
            "day_one": count(
                cohort,
                lambda row: row.get("day_one") and before_cutoff(row["day_one"].get("at")),
            ),
            "video_engaged": count(
                cohort,
                lambda row: any(
                    action.get("label") == "Начал смотреть видео"
                    and before_cutoff(action.get("at"))
                    for action in row.get("other_actions", [])
                ),
            ),
            "end_day_cta": count(
                cohort,
                lambda row: any(
                    action.get("label") in {"Нажал Telegram в интенсиве", "Нажал MAX в интенсиве"}
                    and before_cutoff(action.get("at"))
                    for action in row.get("other_actions", [])
                ),
            ),
            "subscribed": count(
                cohort,
                lambda row: row.get("subscription")
                and before_cutoff(row["subscription"].get("at")),
            ),
        }

    depth = _course_depth_snapshot(db, starts, cutoff)
    acquisition_depth = _course_depth_snapshot(db, attributed_starts, cutoff)
    start_cohort = cohort_metrics(starts)
    acquisition_cohort = cohort_metrics(attributed_starts)
    acquisition_reminders = _reminder_snapshot(db, attributed_starts, cutoff)

    try:
        entry_tracking_from = date.fromisoformat(settings.marketing_report_entry_tracking_from)
        depth_tracking_from = date.fromisoformat(settings.marketing_report_depth_tracking_from)
    except ValueError as error:
        raise RuntimeError("marketing report tracking dates must be YYYY-MM-DD") from error

    entry_tracking_available = report_date >= entry_tracking_from
    tracking_errors = []
    # A delayed Start can legitimately outlive the dashboard's landing-event window.
    # The journey id carried by the bot Start is the durable attribution link.
    unlinked_starts = sum(not row.get("journey_id") for row in starts)
    if entry_tracking_available and unlinked_starts:
        tracking_errors.append(f"У {unlinked_starts} реальных Start нет journey_id посадки")

    return {
        "entries": entry_count,
        "entry_tracking_available": entry_tracking_available,
        "tracking_errors": tracking_errors,
        "starts": start_cohort["starts"],
        "acquisition_starts": acquisition_cohort["starts"],
        "new_leads": sum(bool(row.get("is_new_lead")) for row in starts),
        "personal_or_main_open": start_cohort["personal_or_main_open"],
        "day_one": start_cohort["day_one"],
        "video_engaged": start_cohort["video_engaged"],
        "acquisition_personal_or_main_open": acquisition_cohort["personal_or_main_open"],
        "acquisition_day_one": acquisition_cohort["day_one"],
        "acquisition_video_engaged": acquisition_cohort["video_engaged"],
        "page_depth": depth["page"],
        "video_depth": depth["video"],
        "acquisition_page_depth": acquisition_depth["page"],
        "acquisition_video_depth": acquisition_depth["video"],
        "depth_tracking_available": report_date >= depth_tracking_from,
        "end_day_cta": start_cohort["end_day_cta"],
        "acquisition_end_day_cta": acquisition_cohort["end_day_cta"],
        "subscribed": start_cohort["subscribed"],
        "acquisition_subscribed": acquisition_cohort["subscribed"],
        "reminder_tracking_available": acquisition_reminders["available"],
        "acquisition_reminders_sent": acquisition_reminders["sent"],
        "acquisition_opened_within_3h_after_reminder": acquisition_reminders["opened_within_3h"],
        "by_creative": dict(by_creative),
        "by_messenger": dict(by_messenger),
        "by_method": dict(by_method),
        "by_device": dict(by_device),
    }


def _with_starts(direct: dict, starts: dict[str, int]) -> dict:
    for ad in direct["ads"]:
        candidates = {str(ad["ad_id"]), ad["name"]}
        aliases = {
            1920472171246211821: {"control_jeans", "control_cakes"},
            1920472171246211822: {"cat_bagel"},
            1920472171246211823: {"cat_hudey"},
        }.get(ad["ad_id"], set())
        value = sum(count for key, count in starts.items() if key in candidates | aliases or str(ad["ad_id"]) in key)
        ad["starts"] = value
        ad["click_to_start_percent"] = round(value * 100 / ad["clicks"], 1) if ad["clicks"] else None
        ad["cpa_start_rub"] = round(ad["cost_rub"] / value, 2) if value else None
    total_starts = sum(ad["starts"] for ad in direct["ads"])
    direct["total"]["starts"] = total_starts
    direct["total"]["click_to_start_percent"] = round(total_starts * 100 / direct["total"]["clicks"], 1) if direct["total"]["clicks"] else None
    direct["total"]["cpa_start_rub"] = round(direct["total"]["cost_rub"] / total_starts, 2) if total_starts else None
    return direct


def _pct(value: int, base: int) -> str:
    return f"{value * 100 / base:.1f}%" if base else "—"


def _money(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f} ₽".replace(",", " ")


def _delta(current: float | None, previous: float | None) -> str:
    if current is None or not previous:
        return "нет базы"
    change = (current - previous) * 100 / previous
    return f"{change:+.0f}% ко вчера"


def _table_cell(text: Any, *, header: bool = False, align: str = "left") -> dict:
    cell = {"text": str(text), "align": align, "valign": "middle"}
    if header:
        cell["is_header"] = True
    return cell


def _table(headers: list[str], rows: list[list[Any]], caption: str) -> dict:
    return {
        "type": "table",
        "caption": caption,
        "is_bordered": True,
        "is_striped": True,
        "is_compact": True,
        "cells": [
            [_table_cell(value, header=True, align="left" if index == 0 else "center") for index, value in enumerate(headers)],
            *[
                [_table_cell(value, align="left" if index == 0 else "center") for index, value in enumerate(row)]
                for row in rows
            ],
        ],
    }


def _details(lines: list[str]) -> dict:
    return {
        "type": "details",
        "summary": "Что значат показатели",
        "blocks": [{"type": "paragraph", "text": f"• {line}"} for line in lines],
    }


def _rich_message(title: str, blocks: list[dict], fallback_text: str) -> dict:
    return {
        "rich_message": {
            "blocks": [
                {"type": "heading", "size": 2, "text": title},
                *blocks,
            ]
        },
        "fallback_text": fallback_text,
    }


def _report_period(payload: dict) -> tuple[str, str]:
    report_date = date.fromisoformat(payload["report_date"])
    return (
        report_date.strftime("%d.%m.%Y"),
        (report_date + timedelta(days=1)).strftime("%d.%m.%Y"),
    )


def _funnel_values(payload: dict) -> dict[str, int | None]:
    channels = payload["channels"]
    internal = payload["internal"]
    clicks = sum(item["total"]["clicks"] for item in channels.values())
    sessions_available = all(item["total"].get("sessions_available", True) for item in channels.values())
    sessions = sum(item["total"].get("sessions", 0) for item in channels.values()) if sessions_available else None
    device_sessions: dict[str, int] = defaultdict(int)
    device_sessions_available = sessions_available
    for channel in channels.values():
        for device, values in channel.get("devices", {}).items():
            if not values.get("sessions_available", True):
                device_sessions_available = False
            else:
                device_sessions[device] += int(values.get("sessions") or 0)
    entry_available = bool(internal.get("entry_tracking_available"))
    depth_available = bool(internal.get("depth_tracking_available"))
    reminder_available = bool(internal.get("reminder_tracking_available"))
    button = internal.get("by_method", {}).get("button", {})
    qr = internal.get("by_method", {}).get("qr", {})
    page = internal.get("acquisition_page_depth") or {}
    video = internal.get("acquisition_video_depth") or {}
    return {
        "clicks": clicks,
        "sessions": sessions,
        "mobile": (
            sum(value for key, value in device_sessions.items() if key in {"mobile", "tablet"})
            if device_sessions_available else None
        ),
        "desktop": device_sessions.get("desktop", 0) if device_sessions_available else None,
        "entries": internal.get("entries") if entry_available else None,
        "button": int(button.get("entries") or 0) if entry_available else None,
        "qr": int(qr.get("entries") or 0) if entry_available else None,
        "starts": internal.get("acquisition_starts"),
        "day_one": internal.get("acquisition_day_one"),
        "reminders": internal.get("acquisition_reminders_sent") if reminder_available else None,
        "after_reminder": internal.get("acquisition_opened_within_3h_after_reminder") if reminder_available else None,
        **{f"page_{value}": int(page.get(str(value)) or 0) if depth_available else None for value in (25, 50, 75, 100)},
        "video_start": internal.get("acquisition_video_engaged"),
        **{f"video_{value}": int(video.get(str(value)) or 0) if depth_available else None for value in (25, 50, 75, 100)},
        "end_cta": internal.get("acquisition_end_day_cta"),
        "subscribed": internal.get("acquisition_subscribed"),
    }


def _shown(value: int | None) -> int | str:
    return value if value is not None else "НД"


def _conversion(value: int | None, base: int | None) -> str:
    return _pct(value, base) if value is not None and base is not None else "НД"


FUNNEL_SPECS: tuple[tuple[str, str, str | None], ...] = (
    ("Клики рекламы", "clicks", None),
    ("Посетили посадку", "sessions", "clicks"),
    ("↳ Телефон", "mobile", "sessions"),
    ("↳ ПК", "desktop", "sessions"),
    ("Перешли в бот", "entries", "sessions"),
    ("↳ Кнопка", "button", "entries"),
    ("↳ QR", "qr", "entries"),
    ("Нажали Start", "starts", "entries"),
    ("Открыли день 1", "day_one", "starts"),
    ("↳ Напоминание", "reminders", "starts"),
    ("↳ Открыли ≤3ч", "after_reminder", "reminders"),
    ("Текст 25%", "page_25", "day_one"),
    ("Текст 50%", "page_50", "page_25"),
    ("Текст 75%", "page_75", "page_50"),
    ("Текст 100%", "page_100", "page_75"),
    ("Видео старт", "video_start", "day_one"),
    ("Видео 25%", "video_25", "video_start"),
    ("Видео 50%", "video_50", "video_25"),
    ("Видео 75%", "video_75", "video_50"),
    ("Видео 100%", "video_100", "video_75"),
    ("Кнопка в конце", "end_cta", "day_one"),
    ("Подписались", "subscribed", "end_cta"),
)


def render_messages(payload: dict) -> list[str]:
    channels = payload["channels"]
    internal = payload["internal"]
    day, cutoff_day = _report_period(payload)
    total_clicks = sum(item["total"]["clicks"] for item in channels.values())
    total_cost = sum(item["total"]["cost_rub"] for item in channels.values())
    direct_lines = [
        f"📊 ДИРЕКТ · {day} 00:00–23:59 МСК",
        f"Всего: {total_clicks} рекламных кликов · {_money(total_cost)} · {internal['acquisition_starts']} Start",
    ]
    for key, label in (("rsya", "РСЯ"), ("search", "Поиск")):
        total = channels[key]["total"]
        direct_lines.append(
            f"{label} ИТОГО: {total['clicks']} кликов · CTR {total['ctr_percent']:.2f}% · "
            f"{_money(total['cost_rub'])} · Start {total['starts']} · CPA {_money(total['cpa_start_rub'])}"
        )
        for ad in channels[key]["ads"]:
            direct_lines.append(
                f"  {ad['name']}: {ad['clicks']} · {_money(ad['cost_rub'])} · "
                f"Start {ad['starts']} · CPA {_money(ad['cpa_start_rub'])}"
            )
    funnel = _funnel_values(payload)
    funnel_lines = [f"🧭 ПУТЬ ЛИДА · входы {day}, действия до {cutoff_day} 03:00 МСК"]
    for label, key, parent_key in FUNNEL_SPECS:
        value = funnel.get(key)
        parent = funnel.get(parent_key) if parent_key else None
        parent_conversion = "—" if parent_key is None else _conversion(value, parent)
        funnel_lines.append(
            f"{label}: {_shown(value)} · от шага {parent_conversion} · от клика {_conversion(value, funnel['clicks'])}"
        )
    direct_lines.extend([
        _budget_line("РСЯ", channels["rsya"]),
        _budget_line("Поиск", channels["search"]),
    ])
    if internal.get("tracking_errors"):
        funnel_lines.extend(f"⚠️ {error}" for error in internal["tracking_errors"])
    return ["\n".join(direct_lines) + "\n\n" + "\n".join(funnel_lines)]


def _direct_channel_rows(channel: dict) -> list[list[Any]]:
    total = channel["total"]
    rows = [[
        "ИТОГО", total["impressions"], total["clicks"], f"{total['ctr_percent']:.2f}%",
        _money(total["cost_rub"]), total["starts"], _money(total["cpa_start_rub"]),
    ]]
    rows.extend([
        [
            ad["name"], ad["impressions"], ad["clicks"], f"{ad['ctr_percent']:.2f}%",
            _money(ad["cost_rub"]), ad["starts"], _money(ad["cpa_start_rub"]),
        ]
        for ad in channel["ads"]
    ])
    return rows


def _budget_line(label: str, channel: dict) -> str:
    total = channel["total"]
    limit = total.get("weekly_budget_rub")
    spent = total.get("week_spent_rub")
    remaining = total.get("week_remaining_rub")
    if limit is None or spent is None or remaining is None:
        return f"{label}: недельный остаток НД"
    return f"{label}: неделя {_money(spent)} из {_money(limit)} · осталось {_money(remaining)}"


def render_rich_messages(payload: dict) -> list[dict]:
    channels = payload["channels"]
    internal = payload["internal"]
    previous = payload["comparison_previous"]
    day, cutoff_day = _report_period(payload)
    total_clicks = sum(item["total"]["clicks"] for item in channels.values())
    total_cost = sum(item["total"]["cost_rub"] for item in channels.values())
    fallbacks = render_messages(payload)
    direct_blocks: list[dict] = [
        {"type": "paragraph", "text": f"Период: {day}, 00:00–23:59 МСК"},
    ]
    for key, label in (("rsya", "РСЯ"), ("search", "Поиск")):
        prior = previous[key]["total"]
        direct_blocks.extend([
            _table(
                ["Вариант", "Пок.", "Кл.", "CTR", "Расход", "Start", "CPA"],
                _direct_channel_rows(channels[key]),
                label,
            ),
            {
                "type": "paragraph",
                "text": (
                    f"{label} вчера: {prior['clicks']} кликов · {_money(prior['cost_rub'])} · "
                    f"{prior['starts']} Start · CPA {_money(prior.get('cpa_start_rub'))}"
                ),
            },
        ])
    direct_blocks.extend([
        {
            "type": "footer",
            "text": (
                f"Всего: {total_clicks} кликов · {_money(total_cost)} · {internal['acquisition_starts']} Start.\n"
                f"{_budget_line('РСЯ', channels['rsya'])}\n{_budget_line('Поиск', channels['search'])}"
            ),
        },
        _details([
            "Кл. — клики по рекламе; Пок. — показы.",
            "Start — человек реально нажал Start в Telegram или MAX, а не просто открыл мессенджер.",
            "CPA — расход на один реальный Start.",
            "Расход за день и недельный остаток показаны отдельно.",
        ]),
    ])
    values = _funnel_values(payload)
    entry_available = bool(internal.get("entry_tracking_available"))
    depth_available = bool(internal.get("depth_tracking_available"))
    reminder_available = bool(internal.get("reminder_tracking_available"))
    funnel_rows = []
    for label, key, parent_key in FUNNEL_SPECS:
        value = values.get(key)
        parent = values.get(parent_key) if parent_key else None
        funnel_rows.append([
            label,
            _shown(value),
            "—" if parent_key is None else _conversion(value, parent),
            _conversion(value, values["clicks"]),
        ])
    funnel_blocks: list[dict] = [
        {
            "type": "paragraph",
            "text": f"Входы {day}; Start и дальнейшие действия учитываются до {cutoff_day} 03:00 МСК.",
        },
        _table(["Этап", "Кол-во", "От шага", "От клика"], funnel_rows, "РСЯ + поиск"),
    ]
    if internal.get("tracking_errors"):
        funnel_blocks.append({"type": "paragraph", "text": "⚠️ " + "\n⚠️ ".join(internal["tracking_errors"])})
    funnel_blocks.append(_details([
        "Клик рекламы — клик, зарегистрированный Директом.",
        "Посетили посадку — визиты Метрики после рекламного клика. Визитов иногда больше кликов из-за повторных заходов.",
        "Телефон/ПК — устройство визита посадки; кнопка/QR — способ перехода в мессенджер.",
        "От шага — конверсия от логического родительского этапа; От клика — от всех рекламных кликов.",
        "Напоминание сейчас отправляется через 15 минут, только если день 1 ещё не открыт; следующий ряд — открытие в течение 3 часов после него.",
        "НД — сигнал тогда ещё не собирался или не был связан; это не ноль.",
        f"Сбор входов: {'работает' if entry_available else 'для этого периода ещё не работал'}; глубина: {'работает' if depth_available else 'для этого периода ещё не работала'}; напоминания: {'работают' if reminder_available else 'НД'}.",
    ]))
    return [_rich_message(
        f"📊 Директ и путь лида · {day}",
        [*direct_blocks, *funnel_blocks],
        "\n\n".join(fallbacks),
    )]


def build_daily_report(db: Session, settings: Settings, report_date: date) -> dict:
    campaign_map = _campaigns(settings)
    internal = _internal_snapshot(db, settings, report_date)
    previous_date = report_date - timedelta(days=1)
    previous_internal = _internal_snapshot(db, settings, previous_date)
    baseline = max(date.fromisoformat(settings.marketing_report_baseline_date), report_date - timedelta(days=365))
    week_start = report_date - timedelta(days=report_date.weekday())
    try:
        campaign_budgets = _direct_campaign_budgets(settings, list(campaign_map.values()))
    except (RuntimeError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        # Budget data is useful context, but its temporary absence must not suppress
        # the whole daily acquisition and funnel report.
        campaign_budgets = {}
    direct_rows = _direct_report(
        settings,
        list(campaign_map.values()),
        min(previous_date, baseline, week_start),
        report_date,
    )
    channels: dict[str, dict] = {}
    comparison: dict[str, dict] = {}
    cumulative: dict[str, dict] = {}
    for kind, campaign_id in campaign_map.items():
        campaign_rows = [row for row in direct_rows if int(row.get("CampaignId") or 0) == campaign_id]
        channels[kind] = _with_starts(
            _ensure_known_ads(
                _summarize_direct([row for row in campaign_rows if row.get("Date") == report_date.isoformat()]),
                kind,
            ),
            internal["by_creative"],
        )
        comparison[kind] = _with_starts(
            _ensure_known_ads(
                _summarize_direct([row for row in campaign_rows if row.get("Date") == previous_date.isoformat()]),
                kind,
            ),
            previous_internal["by_creative"],
        )
        cumulative[kind] = _ensure_known_ads(
            _summarize_direct([
                row for row in campaign_rows
                if baseline.isoformat() <= str(row.get("Date")) <= report_date.isoformat()
            ]) if baseline <= report_date else _summarize_direct([]),
            kind,
        )
        week_spent = round(sum(_number(row.get("Cost")) for row in campaign_rows if week_start.isoformat() <= str(row.get("Date")) <= report_date.isoformat()), 2)
        weekly_budget = campaign_budgets.get(campaign_id)
        channels[kind]["total"].update({
            "weekly_budget_rub": weekly_budget,
            "week_spent_rub": week_spent,
            "week_remaining_rub": round(max(weekly_budget - week_spent, 0), 2) if weekly_budget is not None else None,
        })
    payload = {
        "schema_version": 3,
        "report_date": report_date.isoformat(),
        "cutoff": f"{(report_date + timedelta(days=1)).isoformat()}T03:00:00+03:00",
        "channels": channels,
        "comparison_previous": comparison,
        "cumulative_from": baseline.isoformat(),
        "cumulative": cumulative,
        "internal": internal,
        "notes": ["Direct: календарные сутки; бот-воронка: когорта Start этих суток и действия до среза.", "Первые два дня запуска исключены только из накопительного итога."],
    }
    payload["telegram_messages"] = render_messages(payload)
    payload["telegram_rich_messages"] = render_rich_messages(payload)
    return payload


def generate_and_store(db: Session, settings: Settings, report_date: date) -> MarketingDailyReport:
    payload = build_daily_report(db, settings, report_date)
    start = datetime.combine(report_date, dt_time.min, tzinfo=MOSCOW).astimezone(timezone.utc)
    end = datetime.combine(report_date + timedelta(days=1), dt_time(hour=3), tzinfo=MOSCOW).astimezone(timezone.utc)
    row = db.scalar(select(MarketingDailyReport).where(MarketingDailyReport.report_date == report_date.isoformat()))
    if row is None:
        row = MarketingDailyReport(report_date=report_date.isoformat(), period_start=start, period_end=end)
        db.add(row)
    row.payload_json = payload
    row.telegram_messages = payload["telegram_messages"]
    row.delivery_status = "pending"
    row.sent_at = None
    row.delivery_error = None
    db.commit()
    db.refresh(row)
    return row
