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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.marketing_service import marketing_dashboard
from app.models import CourseEvent, MarketingDailyReport


MOSCOW = ZoneInfo("Europe/Moscow")
DIRECT_REPORT_URL = "https://api.direct.yandex.com/json/v5/reports"
CREATIVE_NAMES = {
    1920472171246211821: "Женщина с тортиками",
    1920472171246211822: "Кот с бубликом",
    1920472171246211823: "Кот «Худеть будем?»",
    1920469239931549227: "Поиск · как начать",
    1920469239931549228: "Поиск · без диет и силы воли",
    1920469239931549229: "Поиск · срывы и возврат веса",
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
            "FieldNames": ["Date", "CampaignId", "AdGroupId", "AdId", "Device", "Impressions", "Clicks", "Cost"],
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


def _summarize_direct(rows: list[dict]) -> dict:
    total = {"impressions": 0, "clicks": 0, "cost_rub": 0.0}
    ads: dict[int, dict] = {}
    devices: dict[str, dict] = defaultdict(lambda: {"impressions": 0, "clicks": 0, "cost_rub": 0.0})
    for row in rows:
        impressions = int(row.get("Impressions") or 0)
        clicks = int(row.get("Clicks") or 0)
        cost = _number(row.get("Cost"))
        ad_id = int(row.get("AdId") or 0)
        device = str(row.get("Device") or "UNKNOWN").lower()
        ad = ads.setdefault(ad_id, {"ad_id": ad_id, "name": CREATIVE_NAMES.get(ad_id, str(ad_id)), "impressions": 0, "clicks": 0, "cost_rub": 0.0})
        for target in (total, ad, devices[device]):
            target["impressions"] += impressions
            target["clicks"] += clicks
            target["cost_rub"] += cost
    for target in [total, *ads.values(), *devices.values()]:
        target["cost_rub"] = round(target["cost_rub"], 2)
        target["ctr_percent"] = round(target["clicks"] * 100 / target["impressions"], 2) if target["impressions"] else 0.0
        target["cpc_rub"] = round(target["cost_rub"] / target["clicks"], 2) if target["clicks"] else None
    return {"total": total, "ads": sorted(ads.values(), key=lambda item: item["ad_id"]), "devices": dict(devices)}


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


def _internal_snapshot(db: Session, settings: Settings, report_date: date) -> dict:
    dashboard = marketing_dashboard(
        db,
        settings,
        date_from=report_date,
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
        }

    depth = _course_depth_snapshot(db, starts, cutoff)
    start_cohort = cohort_metrics(starts)
    acquisition_cohort = cohort_metrics(attributed_starts)

    try:
        entry_tracking_from = date.fromisoformat(settings.marketing_report_entry_tracking_from)
        depth_tracking_from = date.fromisoformat(settings.marketing_report_depth_tracking_from)
    except ValueError as error:
        raise RuntimeError("marketing report tracking dates must be YYYY-MM-DD") from error

    entry_tracking_available = report_date >= entry_tracking_from
    tracking_errors = []
    unlinked_starts = sum(not row.get("landing_entry") for row in starts)
    if entry_tracking_available and unlinked_starts:
        tracking_errors.append(f"У {unlinked_starts} реальных Start нет связанного CTA/QR на посадке")

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
        "depth_tracking_available": report_date >= depth_tracking_from,
        "end_day_cta": start_cohort["end_day_cta"],
        "acquisition_end_day_cta": acquisition_cohort["end_day_cta"],
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


def render_messages(payload: dict) -> list[str]:
    channels = payload["channels"]
    internal = payload["internal"]
    previous = payload["comparison_previous"]
    total_clicks = sum(item["total"]["clicks"] for item in channels.values())
    total_cost = sum(item["total"]["cost_rub"] for item in channels.values())
    lines = [
        f"📊 ДИРЕКТ · {payload['report_date']} · СРЕЗ 03:00 МСК",
        f"Всего: {total_clicks} кликов · {_money(total_cost)} · Реальный Start бота: {internal['acquisition_starts']} · CPA {_money(total_cost / internal['acquisition_starts'] if internal['acquisition_starts'] else None)}",
    ]
    for key, label in (("rsya", "РСЯ"), ("search", "Поиск")):
        total = channels[key]["total"]
        prior = previous[key]["total"]
        lines.append(
            f"{label}: {total['clicks']} кл. · CTR {total['ctr_percent']:.2f}% · {_money(total['cost_rub'])} · "
            f"Start {total['starts']} · К→S {_pct(total['starts'], total['clicks'])} · CPA {_money(total['cpa_start_rub'])}\n"
            f"Вчера: {prior['clicks']} кл. · {_money(prior['cost_rub'])} · Start {prior['starts']} · CPA {_money(prior.get('cpa_start_rub'))}"
        )
    if internal.get("tracking_errors"):
        lines.extend(f"⚠️ {error}" for error in internal["tracking_errors"])
    lines.append("Остаток: Direct API не отдаёт")
    messages = ["\n".join(lines)]

    ad_lines = ["ОБЪЯВЛЕНИЯ"]
    for key, label in (("rsya", "РСЯ"), ("search", "Поиск")):
        for ad in channels[key]["ads"]:
            ad_lines.append(
                f"{label} · {ad['name']}: {ad['clicks']} кл. · {_money(ad['cost_rub'])} · "
                f"Start {ad['starts']} · К→S {_pct(ad['starts'], ad['clicks'])} · CPA {_money(ad['cpa_start_rub'])}"
            )
    messages.append("\n".join(ad_lines))

    entry_count: int | None = internal["entries"] if internal.get("entry_tracking_available") else None
    stages: list[tuple[str, int | None]] = [
        ("Клик", total_clicks),
        ("CTA / QR", entry_count),
        ("Реальный Start бота", internal["acquisition_starts"]),
        ("Интенсив", internal["acquisition_personal_or_main_open"]),
        ("День 1", internal["acquisition_day_one"]),
        ("Видео старт", internal["acquisition_video_engaged"]),
        ("Кнопка в конце", internal["acquisition_end_day_cta"]),
    ]
    funnel = ["ВОРОНКА (РСЯ + ПОИСК)"]
    previous_count: int | None = total_clicks
    for label, value in stages:
        if value is None:
            funnel.append(f"{label}: НД · с пред. НД · с клика НД")
        else:
            from_previous = _pct(value, previous_count) if previous_count is not None else "НД"
            funnel.append(f"{label}: {value} · с пред. {from_previous} · с клика {_pct(value, total_clicks)}")
        previous_count = value
    messages.append("\n".join(funnel))

    depth_available = bool(internal.get("depth_tracking_available"))
    page_depth = internal.get("page_depth") or {}
    video_depth = internal.get("video_depth") or {}
    depth = [
        "ГЛУБИНА ДНЯ 1",
        f"Start бота: {internal['starts']}",
        f"Интенсив: {internal['personal_or_main_open']}",
        f"Открыли день 1: {internal['day_one']}",
    ]
    depth.extend(f"Текст {milestone}%: {page_depth.get(str(milestone), 0) if depth_available else 'НД'}" for milestone in (25, 50, 75, 100))
    depth.append(f"Видео старт: {internal['video_engaged']}")
    depth.extend(f"Видео {milestone}%: {video_depth.get(str(milestone), 0) if depth_available else 'НД'}" for milestone in (25, 50, 75, 100))
    messages.append("\n".join(depth))

    methods = ["СПОСОБ ВХОДА"]
    for key, label in (("button", "Кнопка"), ("qr", "QR")):
        data = internal["by_method"].get(key, {})
        if internal.get("entry_tracking_available"):
            entries = int(data.get("entries") or 0)
            starts = int(data.get("starts") or 0)
            methods.append(f"{label}: {entries} входов · {starts} Start · В→S {_pct(starts, entries)}")
        else:
            methods.append(f"{label}: НД")
    messages.append("\n".join(methods))

    return messages


def render_rich_messages(payload: dict) -> list[dict]:
    channels = payload["channels"]
    internal = payload["internal"]
    previous = payload["comparison_previous"]
    total_clicks = sum(item["total"]["clicks"] for item in channels.values())
    total_cost = sum(item["total"]["cost_rub"] for item in channels.values())
    fallbacks = render_messages(payload)

    channel_rows = []
    prior_rows = []
    for key, label in (("rsya", "РСЯ"), ("search", "Поиск")):
        total = channels[key]["total"]
        prior = previous[key]["total"]
        channel_rows.append([
            label,
            total["clicks"],
            f"{total['ctr_percent']:.2f}%",
            _money(total["cost_rub"]),
            total["starts"],
            _pct(total["starts"], total["clicks"]),
            _money(total["cpa_start_rub"]),
        ])
        prior_rows.append([label, prior["clicks"], _money(prior["cost_rub"]), prior["starts"], _money(prior.get("cpa_start_rub"))])
    summary = _rich_message(
        f"📊 Директ · {payload['report_date']}",
        [
            {"type": "paragraph", "text": "Срез 03:00 МСК"},
            _table(["Канал", "Кл.", "CTR", "Расход", "Start", "К→S", "CPA"], channel_rows, "Каналы до Start"),
            _table(["Вчера", "Кл.", "Расход", "Start", "CPA"], prior_rows, "Сравнение"),
            {"type": "footer", "text": f"Всего: {total_clicks} кликов · {_money(total_cost)} · {internal['acquisition_starts']} Start · CPA {_money(total_cost / internal['acquisition_starts'] if internal['acquisition_starts'] else None)}. Остаток Direct API не отдаёт."},
            *(
                [{"type": "paragraph", "text": "⚠️ " + "\n⚠️ ".join(internal.get("tracking_errors") or [])}]
                if internal.get("tracking_errors")
                else []
            ),
            _details([
                "Кл. — рекламные клики.",
                "К→S — доля кликов, закончившихся реальным Start бота.",
                "CPA — рекламный расход на один реальный Start.",
            ]),
        ],
        fallbacks[0],
    )

    ad_rows = []
    for key, label in (("rsya", "РСЯ"), ("search", "Поиск")):
        for ad in channels[key]["ads"]:
            ad_rows.append([
                f"{label} · {ad['name']}", ad["clicks"], _money(ad["cost_rub"]), ad["starts"],
                _pct(ad["starts"], ad["clicks"]), _money(ad["cpa_start_rub"]),
            ])
    ads_message = _rich_message(
        "Объявления",
        [
            _table(["Объявление", "Кл.", "Расход", "Start", "К→S", "CPA"], ad_rows, "РСЯ и поиск"),
            _details([
                "Здесь сравниваются конкретные креативы РСЯ и поисковые объявления.",
                "Решение о победителе принимается не по одному CTR, а по Start, CPA и достаточности данных.",
            ]),
        ],
        fallbacks[1],
    )

    entry_count: int | None = internal["entries"] if internal.get("entry_tracking_available") else None
    stages: list[tuple[str, int | None]] = [
        ("Клик", total_clicks),
        ("CTA / QR", entry_count),
        ("Start бота", internal["acquisition_starts"]),
        ("Интенсив", internal["acquisition_personal_or_main_open"]),
        ("День 1", internal["acquisition_day_one"]),
        ("Видео старт", internal["acquisition_video_engaged"]),
        ("Кнопка в конце", internal["acquisition_end_day_cta"]),
    ]
    funnel_rows = []
    previous_count: int | None = total_clicks
    for label, value in stages:
        shown_value: int | str = value if value is not None else "НД"
        from_previous = _pct(value, previous_count) if value is not None and previous_count is not None else "НД"
        from_click = _pct(value, total_clicks) if value is not None else "НД"
        funnel_rows.append([label, shown_value, from_previous, from_click])
        previous_count = value
    funnel_message = _rich_message(
        "Воронка · РСЯ + поиск",
        [
            _table(["Этап", "Людей", "С пред.", "С клика"], funnel_rows, "Когорта CTA/QR отчётного дня"),
            _details([
                "С пред. — конверсия от предыдущего этапа.",
                "С клика — общая конверсия от рекламного клика.",
                "НД — сигнал не был связан или ещё не был инструментирован; это не ноль.",
            ]),
        ],
        fallbacks[2],
    )

    depth_available = bool(internal.get("depth_tracking_available"))
    page_depth = internal.get("page_depth") or {}
    video_depth = internal.get("video_depth") or {}
    depth_rows = [
        ["Start бота", internal["starts"]],
        ["Интенсив", internal["personal_or_main_open"]],
        ["День 1", internal["day_one"]],
    ]
    depth_rows.extend([f"Текст {milestone}%", page_depth.get(str(milestone), 0) if depth_available else "НД"] for milestone in (25, 50, 75, 100))
    depth_rows.append(["Видео старт", internal["video_engaged"]])
    depth_rows.extend([f"Видео {milestone}%", video_depth.get(str(milestone), 0) if depth_available else "НД"] for milestone in (25, 50, 75, 100))
    depth_message = _rich_message(
        "Глубина дня 1",
        [
            _table(["Этап", "Людей"], depth_rows, "Когорта first Start отчётного дня"),
            _details([
                "Каждый человек учитывается в каждом достигнутом пороге только один раз.",
                "Глубина считается для когорты людей, впервые нажавших Start в отчётные сутки, до среза 03:00 МСК.",
            ]),
        ],
        fallbacks[3],
    )

    method_rows = []
    for key, label in (("button", "Кнопка"), ("qr", "QR")):
        data = internal["by_method"].get(key, {})
        if internal.get("entry_tracking_available"):
            entries = int(data.get("entries") or 0)
            starts = int(data.get("starts") or 0)
            method_rows.append([label, entries, starts, _pct(starts, entries)])
        else:
            method_rows.append([label, "НД", "НД", "НД"])
    method_message = _rich_message(
        "Способ входа",
        [
            _table(["Вход", "Людей", "Start", "В→S"], method_rows, "Кнопка или QR"),
            _details([
                "Вход — зафиксированное нажатие кнопки или открытие QR-кода на посадке.",
                "В→S — доля входов, закончившихся реальным Start бота.",
                "Мессенджер и устройство сохраняются в базе для анализа, но не перегружают ежедневную сводку.",
            ]),
        ],
        fallbacks[4],
    )
    return [summary, ads_message, funnel_message, depth_message, method_message]


def build_daily_report(db: Session, settings: Settings, report_date: date) -> dict:
    campaign_map = _campaigns(settings)
    internal = _internal_snapshot(db, settings, report_date)
    previous_date = report_date - timedelta(days=1)
    previous_internal = _internal_snapshot(db, settings, previous_date)
    baseline = max(date.fromisoformat(settings.marketing_report_baseline_date), report_date - timedelta(days=365))
    direct_rows = _direct_report(settings, list(campaign_map.values()), min(previous_date, baseline), report_date)
    channels: dict[str, dict] = {}
    comparison: dict[str, dict] = {}
    cumulative: dict[str, dict] = {}
    for kind, campaign_id in campaign_map.items():
        campaign_rows = [row for row in direct_rows if int(row.get("CampaignId") or 0) == campaign_id]
        channels[kind] = _with_starts(_summarize_direct([row for row in campaign_rows if row.get("Date") == report_date.isoformat()]), internal["by_creative"])
        comparison[kind] = _with_starts(_summarize_direct([row for row in campaign_rows if row.get("Date") == previous_date.isoformat()]), previous_internal["by_creative"])
        cumulative[kind] = _summarize_direct([row for row in campaign_rows if baseline.isoformat() <= str(row.get("Date")) <= report_date.isoformat()]) if baseline <= report_date else _summarize_direct([])
    payload = {
        "schema_version": 2,
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
    channel_rank = sorted(
        (
            (kind, data["total"].get("cpa_start_rub"))
            for kind, data in channels.items()
            if data["total"].get("cpa_start_rub") is not None
        ),
        key=lambda item: item[1],
    )
    best_channel = ({"rsya": "РСЯ", "search": "Поиск"}.get(channel_rank[0][0], channel_rank[0][0]) if channel_rank else "не определён")
    payload["demo_ai_message"] = (
        "🤖 ИМИТАЦИЯ БУДУЩЕГО ИИ-РАЗБОРА (модель пока не подключена)\n"
        f"\nЛучший канал по цене реального Start: {best_channel}. Это полезнее простого сравнения CTR: дешёвый клик без запуска бота не является лидом.\n"
        "\n"
        "Главный следующий вопрос — где теряются люди между CTA/QR и реальным Start, отдельно для Telegram/MAX и кнопки/QR. "
        "Креатив нельзя отключать только из-за малого CTR: для решения нужны хотя бы около 50 кликов и 15 Start на вариант; до этого вывод предварительный.\n"
        "\n"
        "Сравнение с прошлым маркетологом используем как ориентир по CTR и CPC, но старые «конверсии» не смешиваем с нынешним подтверждённым Start: это разные цели."
    )
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
