import os
from datetime import date
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import Base  # noqa: E402
from app import marketing_daily_report as reports  # noqa: E402
from app.models import MarketingDailyReport  # noqa: E402


def settings():
    return SimpleNamespace(
        yandex_direct_token="token",
        yandex_direct_client_login="",
        marketing_report_campaigns="search:714152601,rsya:714157420",
        marketing_report_baseline_date="2026-09-08",
    )


def direct_rows():
    return [
        {"Date": "2026-09-07", "CampaignId": "714157420", "AdGroupId": "1", "AdId": "1920472171246211821", "Device": "MOBILE", "Impressions": "1000", "Clicks": "100", "Cost": "1000"},
        {"Date": "2026-09-07", "CampaignId": "714152601", "AdGroupId": "2", "AdId": "1920469239931549227", "Device": "DESKTOP", "Impressions": "100", "Clicks": "10", "Cost": "500"},
        {"Date": "2026-09-06", "CampaignId": "714157420", "AdGroupId": "1", "AdId": "1920472171246211821", "Device": "MOBILE", "Impressions": "500", "Clicks": "50", "Cost": "400"},
    ]


def internal_snapshot():
    return {
        "entries": 12,
        "starts": 6,
        "new_leads": 6,
        "personal_or_main_open": 5,
        "day_one": 4,
        "video_engaged": 3,
        "end_day_cta": 2,
        "by_creative": {"control_cakes": 4, "1920469239931549227": 2},
        "by_messenger": {"tg": {"entries": 8, "starts": 5}, "max": {"entries": 4, "starts": 1}},
        "by_method": {"button": {"entries": 10, "starts": 5}, "qr": {"entries": 2, "starts": 1}},
        "by_device": {"mobile": {"entries": 10, "starts": 5}, "desktop": {"entries": 2, "starts": 1}},
    }


def test_report_compares_days_and_uses_real_internal_starts(monkeypatch):
    monkeypatch.setattr(reports, "_direct_report", lambda *_args, **_kwargs: direct_rows())
    monkeypatch.setattr(reports, "_internal_snapshot", lambda *_args, **_kwargs: internal_snapshot())
    payload = reports.build_daily_report(None, settings(), date(2026, 9, 7))

    assert payload["channels"]["rsya"]["total"]["starts"] == 4
    assert payload["channels"]["search"]["total"]["starts"] == 2
    assert payload["comparison_previous"]["rsya"]["total"]["clicks"] == 50
    assert payload["cumulative"]["rsya"]["total"]["clicks"] == 0
    assert any("Реальный Start бота: 6" in message for message in payload["telegram_messages"])
    assert "ИМИТАЦИЯ" in payload["demo_ai_message"]


def test_generate_and_store_replaces_same_daily_snapshot(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(reports, "build_daily_report", lambda *_args, **_kwargs: {"telegram_messages": ["report"], "value": 1})
    with Session(engine) as db:
        reports.generate_and_store(db, settings(), date(2026, 9, 7))
        reports.generate_and_store(db, settings(), date(2026, 9, 7))
        stored = list(db.scalars(select(MarketingDailyReport)))
        assert len(stored) == 1
        assert stored[0].telegram_messages == ["report"]
