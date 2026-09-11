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
    1920472171246211821: "Женщина лицом в торт · без текста",
    1920472171246211822: "Кот с бубликом",
    1920472171246211823: "Кот «Худеть будем?»",
    1921017629943159159: "Холодильник и торт · «Как можно худеть без срывов?»",
    1920469239931549227: "Поиск · как начать",
    1920469239931549228: "Поиск · без диет и силы воли",
    1920469239931549229: "Поиск · срывы и возврат веса",
}
CAMPAIGN_AD_IDS = {
    "rsya": (1920472171246211821, 1920472171246211822, 1920472171246211823, 1921017629943159159),
    "search": (1920469239931549227, 1920469239931549228, 1920469239931549229),
}
DIRECT_CREATIVE_ALIASES = {
    1920472171246211821: {"control_jeans", "control_cakes", "woman_face_cake_no_text"},
    1920472171246211822: {"cat_bagel"},
    1920472171246211823: {"cat_hudey"},
    1921017629943159159: {"fridge_cake_sryvy_v1"},
}


def _creative_name(ad_id: int, rows: list[dict[str, Any]] | None = None) -> str:
    """Return a truthful label for an immutable creative, including legacy mixed IDs."""

    if ad_id != 1920472171246211821:
        return CREATIVE_NAMES.get(ad_id, str(ad_id))
    dates = {str(row.get("Date") or "") for row in rows or []}
    if dates and all(value <= "2026-09-08" for value in dates):
        return "Женщина у холодильника с тортами · без текста (V1)"
    if dates == {"2026-09-09"}:
        return "Переход V1 → V2 внутри одного объявления · не сравнивать"
    if dates and any(value <= "2026-09-09" for value in dates):
        return "Женщина у холодильника / лицом в торт · смешанные версии"
    return "Женщина лицом в светлый торт · без текста (V2)"


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
    ad_rows: dict[int, list[dict]] = defaultdict(list)
    devices: dict[str, dict] = defaultdict(
        lambda: {"impressions": 0, "clicks": 0, "sessions": 0, "sessions_available": True, "cost_rub": 0.0}
    )
    for row in rows:
        impressions = int(row.get("Impressions") or 0)
        clicks = int(row.get("Clicks") or 0)
        sessions = _integer_metric(row.get("Sessions"))
        cost = _number(row.get("Cost"))
        ad_id = int(row.get("AdId") or 0)
        ad_rows[ad_id].append(row)
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
    for ad_id, ad in ads.items():
        ad["name"] = _creative_name(ad_id, ad_rows[ad_id])
    for target in [total, *ads.values(), *devices.values()]:
        target["cost_rub"] = round(target["cost_rub"], 2)
        target["ctr_percent"] = round(target["clicks"] * 100 / target["impressions"], 2) if target["impressions"] else 0.0
        target["cpm_rub"] = round(target["cost_rub"] * 1000 / target["impressions"], 2) if target["impressions"] else None
        target["cpc_rub"] = round(target["cost_rub"] / target["clicks"], 2) if target["clicks"] else None
    return {"total": total, "ads": sorted(ads.values(), key=lambda item: item["ad_id"]), "devices": dict(devices)}


def _ensure_known_ads(summary: dict, kind: str) -> dict:
    # The report is an operational daily view: only served announcements belong
    # here. Archived and paused zero rows remain available in the catalogue.
    del kind
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
        return {"available": False, "sent": 0, "eligible_within_3h": 0, "opened_within_3h": 0}

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
        return {"available": True, "sent": 0, "eligible_within_3h": 0, "opened_within_3h": 0}

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

    eligible_reminders = {
        user_id: sent_at
        for user_id, sent_at in reminder_by_user.items()
        if sent_at + timedelta(hours=3) <= _aware_utc(cutoff)
    }
    opened_within_3h = 0
    for user_id, sent_at in eligible_reminders.items():
        opened_at = day_one_by_user.get(user_id)
        if opened_at and sent_at <= opened_at < _aware_utc(cutoff) and opened_at <= sent_at + timedelta(hours=3):
            opened_within_3h += 1
    return {
        "available": True,
        "sent": len(reminder_by_user),
        "eligible_within_3h": len(eligible_reminders),
        "opened_within_3h": opened_within_3h,
    }


def _internal_snapshot(
    db: Session,
    settings: Settings,
    report_date: date,
    creative_to_channel: dict[str, str] | None = None,
) -> dict:
    dashboard = marketing_dashboard(
        db,
        settings,
        # Query one adjacent day on each side, then apply the exact midnight
        # boundary below to avoid losing a journey at a date boundary.
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
    # Direct closes each day at the next Moscow midnight. The lead funnel uses
    # the identical boundary, so one report never extends into a second day.
    cutoff = datetime.combine(report_date + timedelta(days=1), dt_time.min, tzinfo=MOSCOW)

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

    # The operator's primary comparison is one continuous acquisition path for
    # each creative: landing button → Start → first intensive opening. Keep it
    # alongside the detailed funnel so different ads never borrow one another's
    # conversion values.
    creative_funnel: dict[str, dict[str, int]] = defaultdict(
        lambda: {"button_clicks": 0, "starts": 0, "intensive_opened": 0}
    )
    for item in entry_breakdown:
        creative = str(item.get("creative") or "—")
        if item.get("entry") == "button":
            creative_funnel[creative]["button_clicks"] += int(item.get("entries") or 0)
    for row in attributed_starts:
        creative = str(row.get("creative") or "—")
        creative_funnel[creative]["starts"] += 1
        if row.get("day_one") and before_cutoff(row["day_one"].get("at")):
            creative_funnel[creative]["intensive_opened"] += 1

    depth = _course_depth_snapshot(db, starts, cutoff)
    acquisition_depth = _course_depth_snapshot(db, attributed_starts, cutoff)
    start_cohort = cohort_metrics(starts)
    acquisition_cohort = cohort_metrics(attributed_starts)
    acquisition_reminders = _reminder_snapshot(db, attributed_starts, cutoff)

    def channel_snapshot(channel: str) -> dict:
        def belongs(row: dict) -> bool:
            return creative_to_channel is not None and creative_to_channel.get(str(row.get("creative") or "")) == channel

        channel_starts = [row for row in starts if belongs(row)]
        channel_attributed = [row for row in attributed_starts if belongs(row)]
        channel_breakdown = [
            item for item in entry_breakdown
            if creative_to_channel is not None and creative_to_channel.get(str(item.get("creative") or "")) == channel
        ]
        messenger: dict[str, dict] = defaultdict(lambda: {"entries": 0, "starts": 0})
        method: dict[str, dict] = defaultdict(lambda: {"entries": 0, "starts": 0})
        device: dict[str, dict] = defaultdict(lambda: {"entries": 0, "starts": 0})
        for item in channel_breakdown:
            item_messenger = item.get("messenger") or "не определён"
            item_method = item.get("entry") or "не определён"
            entries = int(item.get("entries") or 0)
            messenger[item_messenger]["entries"] += entries
            method[item_method]["entries"] += entries
        seen_journeys: set[str] = set()
        for row in entry_dashboard.get("rows", []):
            journey_id = str(row.get("journey_id") or "")
            if not belongs(row) or not journey_id or journey_id in seen_journeys:
                continue
            seen_journeys.add(journey_id)
            device[row.get("device") or "не определён"]["entries"] += 1
        for row in channel_attributed:
            row_messenger = row.get("messenger") or "не определён"
            row_method = row.get("entry_method") or "не определён"
            row_device = row.get("device") or "не определён"
            messenger[row_messenger]["starts"] += 1
            method[row_method]["starts"] += 1
            device[row_device]["starts"] += 1
        cohort = cohort_metrics(channel_attributed)
        depth = _course_depth_snapshot(db, channel_attributed, cutoff)
        reminders = _reminder_snapshot(db, channel_attributed, cutoff)
        channel_unlinked_starts = sum(not row.get("journey_id") for row in channel_starts)
        return {
            "entries": sum(int(item.get("entries") or 0) for item in channel_breakdown),
            "starts": len(channel_starts),
            "acquisition_starts": cohort["starts"],
            "acquisition_day_one": cohort["day_one"],
            "acquisition_video_engaged": cohort["video_engaged"],
            "acquisition_end_day_cta": cohort["end_day_cta"],
            "acquisition_subscribed": cohort["subscribed"],
            "acquisition_page_depth": depth["page"],
            "acquisition_video_depth": depth["video"],
            "acquisition_reminders_sent": reminders["sent"],
            "acquisition_reminders_eligible_within_3h": reminders.get("eligible_within_3h", reminders["sent"]),
            "acquisition_opened_within_3h_after_reminder": reminders["opened_within_3h"],
            "by_messenger": dict(messenger),
            "by_method": dict(method),
            "by_device": dict(device),
            "tracking_errors": (
                [f"У {channel_unlinked_starts} реальных Start нет journey_id посадки"]
                if entry_tracking_available and channel_unlinked_starts else []
            ),
        }

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
        "acquisition_reminders_eligible_within_3h": acquisition_reminders.get("eligible_within_3h", acquisition_reminders["sent"]),
        "acquisition_opened_within_3h_after_reminder": acquisition_reminders["opened_within_3h"],
        "by_creative": dict(by_creative),
        "by_creative_funnel": dict(creative_funnel),
        "by_messenger": dict(by_messenger),
        "by_method": dict(by_method),
        "by_device": dict(by_device),
        **({
            "channels": {
                channel: channel_snapshot(channel)
                for channel in sorted(set(creative_to_channel.values()))
            },
        } if creative_to_channel else {}),
    }


def _with_starts(direct: dict, starts: dict[str, int]) -> dict:
    for ad in direct["ads"]:
        candidates = {str(ad["ad_id"]), ad["name"]}
        aliases = DIRECT_CREATIVE_ALIASES.get(ad["ad_id"], set())
        value = sum(count for key, count in starts.items() if key in candidates | aliases or str(ad["ad_id"]) in key)
        ad["starts"] = value
        ad["click_to_start_percent"] = round(value * 100 / ad["clicks"], 1) if ad["clicks"] else None
        ad["cpa_start_rub"] = round(ad["cost_rub"] / value, 2) if value else None
    total_starts = sum(ad["starts"] for ad in direct["ads"])
    direct["total"]["starts"] = total_starts
    direct["total"]["click_to_start_percent"] = round(total_starts * 100 / direct["total"]["clicks"], 1) if direct["total"]["clicks"] else None
    direct["total"]["cpa_start_rub"] = round(direct["total"]["cost_rub"] / total_starts, 2) if total_starts else None
    return direct


def _with_primary_funnel(
    direct: dict,
    creative_funnel: dict[str, dict[str, int]],
    *,
    entry_tracking_available: bool,
) -> dict:
    """Attach the fixed operator comparison path to each served Direct ad."""

    total_buttons: int | None = 0 if entry_tracking_available else None
    total_intensive: int | None = 0 if entry_tracking_available else None
    for ad in direct["ads"]:
        candidates = {str(ad["ad_id"]), ad["name"]} | DIRECT_CREATIVE_ALIASES.get(ad["ad_id"], set())
        button_clicks = (
            sum(int((creative_funnel.get(candidate) or {}).get("button_clicks") or 0) for candidate in candidates)
            if entry_tracking_available else None
        )
        intensive_opened = (
            sum(int((creative_funnel.get(candidate) or {}).get("intensive_opened") or 0) for candidate in candidates)
            if entry_tracking_available else None
        )
        starts = ad["starts"]
        ad.update({"button_clicks": button_clicks, "intensive_opened": intensive_opened})
        ad["landing_to_button_percent"] = round(button_clicks * 100 / ad["sessions"], 1) if button_clicks is not None and ad.get("sessions_available") and ad["sessions"] else None
        ad["button_to_start_percent"] = round(starts * 100 / button_clicks, 1) if button_clicks else None
        ad["start_to_intensive_percent"] = round(intensive_opened * 100 / starts, 1) if intensive_opened is not None and starts else None
        ad["cpo_intensive_rub"] = round(ad["cost_rub"] / intensive_opened, 2) if intensive_opened else None
        if total_buttons is not None:
            total_buttons += button_clicks or 0
        if total_intensive is not None:
            total_intensive += intensive_opened or 0

    total = direct["total"]
    total["button_clicks"] = total_buttons
    total["intensive_opened"] = total_intensive
    total["landing_to_button_percent"] = round(total_buttons * 100 / total["sessions"], 1) if total_buttons is not None and total.get("sessions_available") and total["sessions"] else None
    total["button_to_start_percent"] = round(total["starts"] * 100 / total_buttons, 1) if total_buttons else None
    total["start_to_intensive_percent"] = round(total_intensive * 100 / total["starts"], 1) if total_intensive is not None and total["starts"] else None
    total["cpo_intensive_rub"] = round(total["cost_rub"] / total_intensive, 2) if total_intensive else None
    return direct


def _pct(value: int, base: int) -> str:
    return f"{value * 100 / base:.1f}%" if base else "—"


def _money(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f} ₽".replace(",", " ")


def _rub(value: float | None) -> str:
    return "—" if value is None else f"{value:,.2f} ₽".replace(",", " ").replace(".", ",")


def _stage(value: int | None, conversion: float | None) -> str:
    return "НД" if value is None else f"{value} · {conversion:.1f}%" if conversion is not None else str(value)


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


def _funnel_values(payload: dict, channel: str) -> dict[str, int | None]:
    channels = payload["channels"]
    internal = payload["internal"]
    direct = channels[channel]
    # Stored reports generated before the split have no channel map. New reports
    # must never borrow another channel's funnel when one channel has no traffic.
    channel_internal = internal if "channels" not in internal else internal["channels"].get(channel, {})
    clicks = direct["total"]["clicks"]
    sessions_available = direct["total"].get("sessions_available", True)
    sessions = direct["total"].get("sessions", 0) if sessions_available else None
    device_sessions = direct.get("devices", {})
    entry_available = bool(internal.get("entry_tracking_available"))
    depth_available = bool(internal.get("depth_tracking_available"))
    reminder_available = bool(internal.get("reminder_tracking_available"))
    button = channel_internal.get("by_method", {}).get("button", {})
    qr = channel_internal.get("by_method", {}).get("qr", {})
    page = channel_internal.get("acquisition_page_depth") or {}
    video = channel_internal.get("acquisition_video_depth") or {}
    messenger = channel_internal.get("by_messenger", {})
    return {
        "clicks": clicks,
        "sessions": sessions,
        "mobile": (
            sum(int(value.get("sessions") or 0) for key, value in device_sessions.items() if key in {"mobile", "tablet"})
            if sessions_available else None
        ),
        "desktop": int(device_sessions.get("desktop", {}).get("sessions") or 0) if sessions_available else None,
        "entries": channel_internal.get("entries") if entry_available else None,
        "button": int(button.get("entries") or 0) if entry_available else None,
        "qr": int(qr.get("entries") or 0) if entry_available else None,
        "max": int(messenger.get("max", {}).get("entries") or 0) if entry_available else None,
        "max_starts": int(messenger.get("max", {}).get("starts") or 0) if entry_available else None,
        "telegram": (
            int(messenger.get("tg", {}).get("entries") or 0)
            + int(messenger.get("telegram", {}).get("entries") or 0)
        ) if entry_available else None,
        "telegram_starts": (
            int(messenger.get("tg", {}).get("starts") or 0)
            + int(messenger.get("telegram", {}).get("starts") or 0)
        ) if entry_available else None,
        "starts": channel_internal.get("acquisition_starts"),
        "day_one": channel_internal.get("acquisition_day_one"),
        "reminders": channel_internal.get("acquisition_reminders_sent") if reminder_available else None,
        "reminder_eligible": channel_internal.get("acquisition_reminders_eligible_within_3h") if reminder_available else None,
        "after_reminder": channel_internal.get("acquisition_opened_within_3h_after_reminder") if reminder_available else None,
        **{f"page_{value}": int(page.get(str(value)) or 0) if depth_available else None for value in (25, 50, 75, 100)},
        "video_start": channel_internal.get("acquisition_video_engaged"),
        **{f"video_{value}": int(video.get(str(value)) or 0) if depth_available else None for value in (25, 50, 75, 100)},
        "end_cta": channel_internal.get("acquisition_end_day_cta"),
        "subscribed": channel_internal.get("acquisition_subscribed"),
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
    ("Нажали кнопку мессенджера", "entries", "sessions"),
    ("↳ MAX", "max", "entries"),
    ("↳ Telegram", "telegram", "entries"),
    ("↳ QR-код", "qr", "entries"),
    ("Нажали Start", "starts", "entries"),
    ("Открыли день 1", "day_one", "starts"),
    ("↳ Напоминание", "reminders", "starts"),
    ("↳ Полное окно ≤3ч", "reminder_eligible", "reminders"),
    ("↳ Открыли ≤3ч", "after_reminder", "reminder_eligible"),
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
    day, cutoff_day = _report_period(payload)
    messages = []
    for key, label in (("rsya", "РСЯ"), ("search", "Поиск")):
        total = channels[key]["total"]
        direct_lines = [
            f"📊 {label} · {day} 00:00–{cutoff_day} 00:00 МСК",
            f"ИТОГО: {total['impressions']} показов · {total['clicks']} кликов · CTR {total['ctr_percent']:.2f}% · "
            f"CPM {_rub(total['cpm_rub'])} · CPC {_rub(total['cpc_rub'])} · "
            f"кнопка {_stage(total.get('button_clicks'), total.get('landing_to_button_percent'))} · "
            f"Start {_stage(total.get('starts'), total.get('button_to_start_percent'))} · "
            f"интенсив {_stage(total.get('intensive_opened'), total.get('start_to_intensive_percent'))} · "
            f"CPA Start {_rub(total['cpa_start_rub'])} · CPO интенсив {_rub(total.get('cpo_intensive_rub'))}",
        ]
        direct_lines.extend(
            f"{ad['name']}: {ad['impressions']} · {ad['clicks']} · CTR {ad['ctr_percent']:.2f}% · "
            f"CPM {_rub(ad['cpm_rub'])} · CPC {_rub(ad['cpc_rub'])} · "
            f"кнопка {_stage(ad.get('button_clicks'), ad.get('landing_to_button_percent'))} · "
            f"Start {_stage(ad.get('starts'), ad.get('button_to_start_percent'))} · "
            f"интенсив {_stage(ad.get('intensive_opened'), ad.get('start_to_intensive_percent'))} · "
            f"CPA Start {_rub(ad['cpa_start_rub'])} · CPO интенсив {_rub(ad.get('cpo_intensive_rub'))}"
            for ad in channels[key]["ads"]
        )
        funnel = _funnel_values(payload, key)
        funnel_lines = [f"🧭 ПУТЬ ЛИДА · входы и действия {day} 00:00–{cutoff_day} 00:00 МСК"]
        for label_text, funnel_key, parent_key in FUNNEL_SPECS:
            value = funnel.get(funnel_key)
            parent = funnel.get(parent_key) if parent_key else None
            parent_conversion = "—" if parent_key is None else _conversion(value, parent)
            funnel_lines.append(
                f"{label_text}: {_shown(value)} · от шага {parent_conversion} · от клика {_conversion(value, funnel['clicks'])}"
            )
        funnel_lines.extend([
            "Мессенджеры · CTA → Start:",
            f"↳ MAX: CTA {_shown(funnel['max'])} · Start {_shown(funnel['max_starts'])} · {_conversion(funnel['max_starts'], funnel['max'])}",
            f"↳ Telegram: CTA {_shown(funnel['telegram'])} · Start {_shown(funnel['telegram_starts'])} · {_conversion(funnel['telegram_starts'], funnel['telegram'])}",
        ])
        direct_lines.append(_budget_line(label, channels[key]))
        messages.append("\n".join(direct_lines) + "\n\n" + "\n".join(funnel_lines))
    return messages


def _direct_channel_rows(channel: dict) -> list[list[Any]]:
    total = channel["total"]
    rows = [[
        "ИТОГО", total["impressions"], f"{total['clicks']} · {total['ctr_percent']:.2f}%",
        _rub(total["cpm_rub"]), _money(total["cost_rub"]), _rub(total["cpc_rub"]),
        _stage(total.get("button_clicks"), total.get("landing_to_button_percent")),
        _stage(total.get("starts"), total.get("button_to_start_percent")),
        _stage(total.get("intensive_opened"), total.get("start_to_intensive_percent")),
        _rub(total["cpa_start_rub"]), _rub(total.get("cpo_intensive_rub")),
    ]]
    rows.extend([
        [
            ad["name"], ad["impressions"], f"{ad['clicks']} · {ad['ctr_percent']:.2f}%",
            _rub(ad["cpm_rub"]), _money(ad["cost_rub"]), _rub(ad["cpc_rub"]),
            _stage(ad.get("button_clicks"), ad.get("landing_to_button_percent")),
            _stage(ad.get("starts"), ad.get("button_to_start_percent")),
            _stage(ad.get("intensive_opened"), ad.get("start_to_intensive_percent")),
            _rub(ad["cpa_start_rub"]), _rub(ad.get("cpo_intensive_rub")),
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


def _channel_rich_message(payload: dict, channel: str, label: str, fallback_text: str) -> dict:
    channels = payload["channels"]
    internal = payload["internal"]
    previous = payload["comparison_previous"]
    day, cutoff_day = _report_period(payload)
    prior = previous[channel]["total"]
    direct_blocks: list[dict] = [
        {"type": "paragraph", "text": f"Период: {day}, 00:00–{cutoff_day} 00:00 МСК"},
        _table(
            ["Вариант", "Пок.", "Кл. · CTR", "CPM", "Расход", "CPC", "Кнопка / посадка", "Start / кнопка", "Интенсив / Start", "CPA Start", "CPO интенсив"],
            _direct_channel_rows(channels[channel]),
            label,
        ),
        {"type": "paragraph", "text": (
            f"{label} вчера: {prior['impressions']} показов · {prior['clicks']} кликов · "
            f"{_money(prior['cost_rub'])} · Start {prior['starts']} · CPA {_money(prior.get('cpa_start_rub'))}"
        )},
        {"type": "footer", "text": _budget_line(label, channels[channel])},
    ]
    values = _funnel_values(payload, channel)
    channel_internal = internal if "channels" not in internal else internal["channels"].get(channel, {})
    funnel_rows = []
    for label_text, key, parent_key in FUNNEL_SPECS:
        value = values.get(key)
        parent = values.get(parent_key) if parent_key else None
        funnel_rows.append([
            label_text,
            _shown(value),
            "—" if parent_key is None else _conversion(value, parent),
            _conversion(value, values["clicks"]),
        ])
    funnel_blocks: list[dict] = [
        {
            "type": "paragraph",
            "text": f"Входы и действия: {day} 00:00–{cutoff_day} 00:00 МСК.",
        },
        _table(["Этап", "Кол-во", "От шага", "От клика"], funnel_rows, f"Путь лида · {label}"),
        _table(
            ["Мессенджер", "CTA", "Start", "CTA → Start"],
            [
                ["MAX", _shown(values["max"]), _shown(values["max_starts"]), _conversion(values["max_starts"], values["max"])],
                ["Telegram", _shown(values["telegram"]), _shown(values["telegram_starts"]), _conversion(values["telegram_starts"], values["telegram"])],
                ["QR-код", _shown(values["qr"]), "—", "—"],
            ],
            f"Мессенджеры · {label}",
        ),
    ]
    if channel_internal.get("tracking_errors"):
        funnel_blocks.append({"type": "paragraph", "text": "⚠️ " + "\n⚠️ ".join(channel_internal["tracking_errors"])})
    funnel_blocks.append(_details([
        "Клик рекламы — клик, зарегистрированный Директом.",
        "Посетили посадку — визиты Метрики после рекламного клика. Визитов иногда больше кликов из-за повторных заходов.",
        "MAX/Telegram — выбранный на посадке мессенджер; QR-код выводится отдельно, если им воспользовались.",
        "Полное окно ≤3ч — только те, кому после напоминания успели дать все три часа до полуночи; это защищает отчёт от ложного нуля у поздних лидов.",
        "От шага — конверсия от логического родительского этапа; От клика — от всех рекламных кликов.",
        "НД — сигнал тогда ещё не собирался или не был связан; это не ноль.",
    ]))
    return _rich_message(
        f"📊 {label} и путь лида · {day}",
        [*direct_blocks, *funnel_blocks],
        fallback_text,
    )


def render_rich_messages(payload: dict) -> list[dict]:
    fallbacks = render_messages(payload)
    return [
        _channel_rich_message(payload, "rsya", "РСЯ", fallbacks[0]),
        _channel_rich_message(payload, "search", "Поиск", fallbacks[1]),
    ]


def build_daily_report(db: Session, settings: Settings, report_date: date) -> dict:
    campaign_map = _campaigns(settings)
    previous_date = report_date - timedelta(days=1)
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
    campaign_to_channel = {campaign_id: kind for kind, campaign_id in campaign_map.items()}
    creative_to_channel = {
        str(row.get("AdId")): campaign_to_channel[int(row.get("CampaignId") or 0)]
        for row in direct_rows
        if int(row.get("CampaignId") or 0) in campaign_to_channel and row.get("AdId")
    }
    for raw_ad_id, channel in list(creative_to_channel.items()):
        creative_to_channel.update({alias: channel for alias in DIRECT_CREATIVE_ALIASES.get(int(raw_ad_id), set())})
    internal = _internal_snapshot(db, settings, report_date, creative_to_channel)
    previous_internal = _internal_snapshot(db, settings, previous_date, creative_to_channel)
    channels: dict[str, dict] = {}
    comparison: dict[str, dict] = {}
    cumulative: dict[str, dict] = {}
    for kind, campaign_id in campaign_map.items():
        campaign_rows = [row for row in direct_rows if int(row.get("CampaignId") or 0) == campaign_id]
        channels[kind] = _with_primary_funnel(
            _with_starts(
                _ensure_known_ads(
                    _summarize_direct([row for row in campaign_rows if row.get("Date") == report_date.isoformat()]),
                    kind,
                ),
                internal["by_creative"],
            ),
            internal.get("by_creative_funnel", {}),
            entry_tracking_available=bool(internal.get("entry_tracking_available")),
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
        "cutoff": f"{(report_date + timedelta(days=1)).isoformat()}T00:00:00+03:00",
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
    end = datetime.combine(report_date + timedelta(days=1), dt_time.min, tzinfo=MOSCOW).astimezone(timezone.utc)
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
