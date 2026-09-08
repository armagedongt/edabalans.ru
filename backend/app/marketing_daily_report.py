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
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.marketing_service import marketing_dashboard
from app.models import MarketingDailyReport


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


def _internal_snapshot(db: Session, settings: Settings, report_date: date) -> dict:
    dashboard = marketing_dashboard(
        db,
        settings,
        date_from=report_date,
        date_to=report_date + timedelta(days=1),
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

    starts = [row for row in rows if row.get("start") and _moscow_date(row["start"]["at"]) == report_date]
    entries = [row for row in rows if row.get("landing_entry") and _moscow_date(row["landing_entry"]["at"]) == report_date]

    by_creative: dict[str, int] = defaultdict(int)
    by_messenger: dict[str, dict] = defaultdict(lambda: {"entries": 0, "starts": 0})
    by_method: dict[str, dict] = defaultdict(lambda: {"entries": 0, "starts": 0})
    by_device: dict[str, dict] = defaultdict(lambda: {"entries": 0, "starts": 0})
    started_journeys = {row.get("journey_id") for row in starts if row.get("journey_id")}
    for row in starts:
        by_creative[row.get("creative") or "—"] += 1
    for row in entries:
        started = int(row.get("journey_id") in started_journeys)
        messenger = row.get("messenger") or "не определён"
        method = (row.get("landing_entry") or {}).get("method") or "не определён"
        device = row.get("device") or "не определён"
        for bucket, key in ((by_messenger, messenger), (by_method, method), (by_device, device)):
            bucket[key]["entries"] += 1
            bucket[key]["starts"] += started

    def count(predicate) -> int:
        return sum(bool(predicate(row)) for row in starts)

    return {
        "entries": len(entries),
        "starts": len(starts),
        "new_leads": sum(bool(row.get("is_new_lead")) for row in starts),
        "personal_or_main_open": count(lambda row: (row.get("site_home") and before_cutoff(row["site_home"].get("at"))) or any(action.get("label") == "Открыл персональную ссылку интенсива" and before_cutoff(action.get("at")) for action in row.get("other_actions", []))),
        "day_one": count(lambda row: row.get("day_one") and before_cutoff(row["day_one"].get("at"))),
        "video_engaged": count(lambda row: any(action.get("label") == "Начал смотреть видео" and before_cutoff(action.get("at")) for action in row.get("other_actions", []))),
        "end_day_cta": count(lambda row: any(action.get("label") in {"Нажал Telegram в интенсиве", "Нажал MAX в интенсиве"} and before_cutoff(action.get("at")) for action in row.get("other_actions", []))),
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


def _delta(current: float, previous: float) -> str:
    if not previous:
        return "нет базы"
    change = (current - previous) * 100 / previous
    return f"{change:+.0f}% ко вчера"


def render_messages(payload: dict) -> list[str]:
    channels = payload["channels"]
    internal = payload["internal"]
    previous = payload["comparison_previous"]
    total_clicks = sum(item["total"]["clicks"] for item in channels.values())
    total_cost = sum(item["total"]["cost_rub"] for item in channels.values())
    messages = [
        f"📊 Реклама · {payload['report_date']} · срез 03:00 МСК\n"
        f"Расход: {_money(total_cost)} · клики: {total_clicks} · реальные Start: {internal['starts']} · цена Start: {_money(total_cost / internal['starts'] if internal['starts'] else None)}\n"
        "Остаток: Direct API v5 не отдаёт баланс счёта; проверяется отдельно в кабинете.\n"
        f"Ошибок нет",
    ]
    lines = ["КАНАЛЫ (до Start)", "канал | показы | клики | CTR | расход | Start | CPA"]
    for key, label in (("rsya", "РСЯ"), ("search", "Поиск")):
        total = channels[key]["total"]
        prior = previous[key]["total"]
        lines.append(
            f"{label}: {total['impressions']} | {total['clicks']} | {total['ctr_percent']:.2f}% | {_money(total['cost_rub'])} | {total['starts']} | {_money(total['cpa_start_rub'])} ({_delta(total['cost_rub'], prior['cost_rub'])})"
        )
    messages.append("\n".join(lines))

    ad_lines = ["ОБЪЯВЛЕНИЯ", "название | клики | расход | Start | клик→Start | CPA"]
    for key in ("rsya", "search"):
        for ad in channels[key]["ads"]:
            ad_lines.append(
                f"{ad['name']}: {ad['clicks']} | {_money(ad['cost_rub'])} | {ad['starts']} | {_pct(ad['starts'], ad['clicks'])} | {_money(ad['cpa_start_rub'])}"
            )
    messages.append("\n".join(ad_lines))

    stages = [
        ("Клик по рекламе", total_clicks),
        ("CTA/QR на посадке", internal["entries"]),
        ("Реальный Start бота", internal["starts"]),
        ("Открыли интенсив", internal["personal_or_main_open"]),
        ("Открыли день 1", internal["day_one"]),
        ("Включили видео", internal["video_engaged"]),
        ("Кнопка в конце дня", internal["end_day_cta"]),
    ]
    funnel = ["ВОРОНКА (РСЯ + поиск)", "этап | людей | от прошлого | от клика"]
    previous_count = total_clicks
    for label, value in stages:
        funnel.append(f"{label}: {value} | {_pct(value, previous_count)} | {_pct(value, total_clicks)}")
        previous_count = value
    messages.append("\n".join(funnel))

    segment = ["СЕГМЕНТЫ: входы → реальные Start"]
    for title, key in (("Мессенджер", "by_messenger"), ("Способ", "by_method"), ("Устройство посадки", "by_device")):
        values = internal[key]
        segment.append(title + ": " + ("; ".join(f"{name} {data['entries']}→{data['starts']} ({_pct(data['starts'], data['entries'])})" for name, data in sorted(values.items())) or "данных нет"))
    messages.append("\n".join(segment))

    ads = [ad for channel in channels.values() for ad in channel["ads"] if ad["clicks"]]
    with_starts = [ad for ad in ads if ad["starts"]]
    best = min(with_starts, key=lambda ad: ad["cpa_start_rub"]) if with_starts else None
    worst = max(with_starts, key=lambda ad: ad["cpa_start_rub"]) if with_starts else None
    analysis = ["АВТОРАЗБОР БЕЗ ИИ"]
    if best:
        analysis.append(f"• Лучший наблюдаемый вариант: {best['name']} — CPA Start {_money(best['cpa_start_rub'])}.")
    if worst and worst is not best:
        analysis.append(f"• Самый дорогой из вариантов со Start: {worst['name']} — {_money(worst['cpa_start_rub'])}.")
    insufficient = [ad["name"] for ad in ads if ad["clicks"] < 50 or ad["starts"] < 15]
    if insufficient:
        analysis.append("• Решение рано принимать: недостаточно данных у " + ", ".join(insufficient) + ".")
    analysis.append("• Сравнение учитывает вчерашний период; накопительный итог хранится отдельно с 08.09, первые два дня исключены как артефакт запуска.")
    messages.append("\n".join(analysis))
    return messages


def build_daily_report(db: Session, settings: Settings, report_date: date) -> dict:
    campaign_map = _campaigns(settings)
    internal = _internal_snapshot(db, settings, report_date)
    previous_date = report_date - timedelta(days=1)
    baseline = max(date.fromisoformat(settings.marketing_report_baseline_date), report_date - timedelta(days=365))
    direct_rows = _direct_report(settings, list(campaign_map.values()), min(previous_date, baseline), report_date)
    channels: dict[str, dict] = {}
    comparison: dict[str, dict] = {}
    cumulative: dict[str, dict] = {}
    for kind, campaign_id in campaign_map.items():
        campaign_rows = [row for row in direct_rows if int(row.get("CampaignId") or 0) == campaign_id]
        channels[kind] = _with_starts(_summarize_direct([row for row in campaign_rows if row.get("Date") == report_date.isoformat()]), internal["by_creative"])
        comparison[kind] = _summarize_direct([row for row in campaign_rows if row.get("Date") == previous_date.isoformat()])
        cumulative[kind] = _summarize_direct([row for row in campaign_rows if baseline.isoformat() <= str(row.get("Date")) <= report_date.isoformat()]) if baseline <= report_date else _summarize_direct([])
    payload = {
        "schema_version": 1,
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
        f"Лучший канал по цене реального Start: {best_channel}. Это полезнее простого сравнения CTR: дешёвый клик без запуска бота не является лидом.\n"
        "Главный следующий вопрос — где теряются люди между CTA/QR и реальным Start, отдельно для Telegram/MAX и кнопки/QR. "
        "Креатив нельзя отключать только из-за малого CTR: для решения нужны хотя бы около 50 кликов и 15 Start на вариант; до этого вывод предварительный.\n"
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
