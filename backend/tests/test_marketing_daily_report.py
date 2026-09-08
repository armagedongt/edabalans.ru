import os
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import Base  # noqa: E402
from app import marketing_daily_report as reports  # noqa: E402
from app.models import CourseEvent, MarketingDailyReport, User  # noqa: E402


def settings():
    return SimpleNamespace(
        yandex_direct_token="token",
        yandex_direct_client_login="",
        marketing_report_campaigns="search:714152601,rsya:714157420",
        marketing_report_baseline_date="2026-09-08",
        marketing_report_entry_tracking_from="2026-09-08",
        marketing_report_depth_tracking_from="2026-09-09",
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
        "entry_tracking_available": True,
        "tracking_errors": [],
        "starts": 6,
        "acquisition_starts": 6,
        "new_leads": 6,
        "personal_or_main_open": 5,
        "day_one": 4,
        "video_engaged": 3,
        "acquisition_personal_or_main_open": 5,
        "acquisition_day_one": 4,
        "acquisition_video_engaged": 3,
        "page_depth": {"25": 4, "50": 3, "75": 2, "100": 1},
        "video_depth": {"25": 3, "50": 2, "75": 1, "100": 1},
        "depth_tracking_available": True,
        "end_day_cta": 2,
        "acquisition_end_day_cta": 2,
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
    assert all("АВТОРАЗБОР БЕЗ ИИ" not in message for message in payload["telegram_messages"])
    assert [message.splitlines()[0] for message in payload["telegram_messages"]] == [
        "📊 ДИРЕКТ · 2026-09-07 · СРЕЗ 03:00 МСК",
        "ОБЪЯВЛЕНИЯ",
        "ВОРОНКА (РСЯ + ПОИСК)",
        "ГЛУБИНА ДНЯ 1",
        "СПОСОБ ВХОДА",
    ]
    assert len(payload["telegram_rich_messages"]) == 5
    assert [message["rich_message"]["blocks"][0]["text"] for message in payload["telegram_rich_messages"]] == [
        "📊 Директ · 2026-09-07",
        "Объявления",
        "Воронка · РСЯ + поиск",
        "Глубина дня 1",
        "Способ входа",
    ]
    assert [message["fallback_text"] for message in payload["telegram_rich_messages"]] == payload["telegram_messages"]
    summary_headers = [cell["text"] for cell in payload["telegram_rich_messages"][0]["rich_message"]["blocks"][2]["cells"][0]]
    assert summary_headers == ["Канал", "Кл.", "CTR", "Расход", "Start", "К→S", "CPA"]
    assert payload["telegram_rich_messages"][1]["rich_message"]["blocks"][1]["type"] == "table"
    assert payload["telegram_rich_messages"][1]["rich_message"]["blocks"][1]["is_bordered"] is True
    assert payload["telegram_rich_messages"][2]["rich_message"]["blocks"][1]["cells"][0][2]["text"] == "С пред."
    assert payload["telegram_rich_messages"][2]["rich_message"]["blocks"][1]["cells"][1][1]["align"] == "center"
    assert payload["telegram_rich_messages"][2]["rich_message"]["blocks"][2]["type"] == "details"
    depth_cells = payload["telegram_rich_messages"][3]["rich_message"]["blocks"][1]["cells"]
    assert depth_cells[4][0]["text"] == "Текст 25%"
    assert depth_cells[4][1]["text"] == "4"
    assert depth_cells[-1][0]["text"] == "Видео 100%"
    assert "ИМИТАЦИЯ" in payload["demo_ai_message"]
    assert "\n\nЛучший канал" in payload["demo_ai_message"]


def test_course_depth_snapshot_counts_unique_day_one_milestones_after_start():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    user_id = uuid4()
    with Session(engine) as db:
        db.add(User(id=user_id, display_name="Reader", status="active"))
        db.add_all([
            CourseEvent(
                user_id=user_id,
                course_code="intensive",
                event_key="page:1:25",
                event_type="page_progress",
                details={"day": 1, "progress_percent": 25},
                occurred_at=datetime(2026, 9, 7, 9, 5, tzinfo=timezone.utc),
            ),
            CourseEvent(
                user_id=user_id,
                course_code="intensive",
                event_key="page:1:25:duplicate-client-event",
                event_type="page_progress",
                details={"day": 1, "progress_percent": 25},
                occurred_at=datetime(2026, 9, 7, 9, 6, tzinfo=timezone.utc),
            ),
            CourseEvent(
                user_id=user_id,
                course_code="intensive",
                event_key="page:1:50:before-start",
                event_type="page_progress",
                details={"day": 1, "progress_percent": 50},
                occurred_at=datetime(2026, 9, 7, 8, 55, tzinfo=timezone.utc),
            ),
            CourseEvent(
                user_id=user_id,
                course_code="intensive",
                event_key="page:1:75:after-cutoff",
                event_type="page_progress",
                details={"day": 1, "progress_percent": 75},
                occurred_at=datetime(2026, 9, 8, 0, 1, tzinfo=timezone.utc),
            ),
            CourseEvent(
                user_id=user_id,
                course_code="intensive",
                event_key="page:2:100",
                event_type="page_progress",
                details={"day": 2, "progress_percent": 100},
                occurred_at=datetime(2026, 9, 7, 9, 8, tzinfo=timezone.utc),
            ),
            CourseEvent(
                user_id=user_id,
                course_code="intensive",
                event_key="video:1:50",
                event_type="video_progress",
                details={"day": 1, "progress_percent": 50},
                occurred_at=datetime(2026, 9, 7, 9, 10, tzinfo=timezone.utc),
            ),
            CourseEvent(
                user_id=user_id,
                course_code="intensive",
                event_key="video:1:complete",
                event_type="video_complete",
                details={"day": 1, "progress_percent": 100},
                occurred_at=datetime(2026, 9, 7, 9, 15, tzinfo=timezone.utc),
            ),
        ])
        db.commit()
        starts = [{"user_id": str(user_id), "start": {"at": "2026-09-07T09:00:00+00:00"}}]
        result = reports._course_depth_snapshot(
            db,
            starts,
            datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc),
        )

    assert result["page"] == {"25": 1, "50": 0, "75": 0, "100": 0}
    assert result["video"] == {"25": 0, "50": 1, "75": 0, "100": 1}


def test_rich_report_marks_unlinked_landing_signal_as_no_data():
    snapshot = internal_snapshot()
    snapshot.update({"entries": 0, "entry_tracking_available": False})
    payload = {
        "report_date": "2026-09-07",
        "channels": {
            "rsya": reports._with_starts(reports._summarize_direct([direct_rows()[0]]), snapshot["by_creative"]),
            "search": reports._with_starts(reports._summarize_direct([direct_rows()[1]]), snapshot["by_creative"]),
        },
        "comparison_previous": {
            "rsya": reports._with_starts(reports._summarize_direct([]), {}),
            "search": reports._with_starts(reports._summarize_direct([]), {}),
        },
        "internal": snapshot,
    }

    rich = reports.render_rich_messages(payload)
    funnel_cells = rich[2]["rich_message"]["blocks"][1]["cells"]
    assert funnel_cells[2][1]["text"] == "НД"
    method_cells = rich[4]["rich_message"]["blocks"][1]["cells"]
    assert method_cells[1][1]["text"] == "НД"


def test_entry_tracking_availability_comes_from_rollout_date_not_event_count(monkeypatch):
    monkeypatch.setattr(reports, "marketing_dashboard", lambda *_args, **_kwargs: {"rows": []})

    before = reports._internal_snapshot(None, settings(), date(2026, 9, 7))
    after = reports._internal_snapshot(None, settings(), date(2026, 9, 8))

    assert before["entries"] == 0
    assert before["entry_tracking_available"] is False
    assert after["entries"] == 0
    assert after["entry_tracking_available"] is True


def test_internal_snapshot_separates_first_start_cohort_from_click_day_attribution(monkeypatch):
    report_day = date(2026, 9, 8)
    base_row = {
        "user_id": str(uuid4()),
        "source": "Яндекс",
        "is_new_lead": True,
        "creative": "control_cakes",
        "messenger": "telegram",
        "entry_method": "button",
        "device": "mobile",
        "landing_entry": {"at": "2026-09-08T18:00:00+03:00", "method": "button"},
        "start": {"at": "2026-09-08T18:01:00+03:00"},
        "other_actions": [],
    }
    repeat_row = {**base_row, "user_id": str(uuid4()), "is_new_lead": False}
    organic_row = {**base_row, "user_id": str(uuid4()), "source": "Telegram"}
    next_night_row = {
        **base_row,
        "user_id": str(uuid4()),
        "creative": "cat_hudey",
        "start": {"at": "2026-09-09T02:00:00+03:00"},
    }
    after_cutoff_row = {
        **base_row,
        "user_id": str(uuid4()),
        "creative": "too_late",
        "start": {"at": "2026-09-09T03:00:00+03:00"},
    }
    entry_payload = {
        "rows": [base_row],
        "entry_breakdown": [{
            "source": "Яндекс",
            "messenger": "telegram",
            "entry": "button",
            "entries": 3,
        }],
    }
    extended_payload = {"rows": [base_row, repeat_row, organic_row, next_night_row, after_cutoff_row]}

    def dashboard(*_args, **kwargs):
        return entry_payload if kwargs["date_to"] == report_day else extended_payload

    monkeypatch.setattr(reports, "marketing_dashboard", dashboard)
    monkeypatch.setattr(
        reports,
        "_course_depth_snapshot",
        lambda *_args, **_kwargs: {"page": {str(value): 0 for value in (25, 50, 75, 100)}, "video": {str(value): 0 for value in (25, 50, 75, 100)}},
    )

    result = reports._internal_snapshot(None, settings(), report_day)

    assert result["starts"] == 1
    assert result["acquisition_starts"] == 2
    assert result["entries"] == 3
    assert result["by_creative"] == {"control_cakes": 1, "cat_hudey": 1}
    assert result["by_method"]["button"] == {"entries": 3, "starts": 2}


def test_calendar_start_cohort_keeps_previous_evening_landing_link(monkeypatch):
    report_day = date(2026, 9, 9)
    linked_night_start = {
        "user_id": str(uuid4()),
        "journey_id": "journey-night",
        "source": "Яндекс",
        "is_new_lead": True,
        "creative": "control_cakes",
        "messenger": "telegram",
        "entry_method": "button",
        "device": "mobile",
        "landing_entry": {"at": "2026-09-08T23:50:00+03:00", "method": "button"},
        "start": {"at": "2026-09-09T02:00:00+03:00"},
        "other_actions": [],
    }
    calls = []

    def dashboard(*_args, **kwargs):
        calls.append((kwargs["date_from"], kwargs["date_to"]))
        if kwargs["date_from"] == report_day:
            return {"rows": [], "entry_breakdown": []}
        return {"rows": [linked_night_start]}

    monkeypatch.setattr(reports, "marketing_dashboard", dashboard)
    monkeypatch.setattr(
        reports,
        "_course_depth_snapshot",
        lambda *_args, **_kwargs: {
            "page": {str(value): 0 for value in (25, 50, 75, 100)},
            "video": {str(value): 0 for value in (25, 50, 75, 100)},
        },
    )

    result = reports._internal_snapshot(None, settings(), report_day)

    assert calls[0] == (date(2026, 9, 8), date(2026, 9, 10))
    assert result["starts"] == 1
    assert result["tracking_errors"] == []


def test_delayed_start_with_durable_journey_id_is_not_an_attribution_error(monkeypatch):
    report_day = date(2026, 9, 11)
    delayed_start = {
        "user_id": str(uuid4()),
        "journey_id": "journey-from-two-days-ago",
        "source": "Яндекс",
        "is_new_lead": True,
        "creative": "control_cakes",
        "messenger": "telegram",
        "entry_method": "button",
        "device": "mobile",
        "landing_entry": None,
        "start": {"at": "2026-09-11T12:00:00+03:00"},
        "other_actions": [],
    }

    monkeypatch.setattr(
        reports,
        "marketing_dashboard",
        lambda *_args, **kwargs: (
            {"rows": [], "entry_breakdown": []}
            if kwargs["date_from"] == report_day
            else {"rows": [delayed_start]}
        ),
    )
    monkeypatch.setattr(
        reports,
        "_course_depth_snapshot",
        lambda *_args, **_kwargs: {
            "page": {str(value): 0 for value in (25, 50, 75, 100)},
            "video": {str(value): 0 for value in (25, 50, 75, 100)},
        },
    )

    result = reports._internal_snapshot(None, settings(), report_day)

    assert result["starts"] == 1
    assert result["tracking_errors"] == []


def test_depth_tracking_availability_has_independent_rollout_boundary(monkeypatch):
    monkeypatch.setattr(reports, "marketing_dashboard", lambda *_args, **_kwargs: {"rows": []})
    monkeypatch.setattr(
        reports,
        "_course_depth_snapshot",
        lambda *_args, **_kwargs: {
            "page": {str(value): 0 for value in (25, 50, 75, 100)},
            "video": {str(value): 0 for value in (25, 50, 75, 100)},
        },
    )

    before = reports._internal_snapshot(None, settings(), date(2026, 9, 8))
    after = reports._internal_snapshot(None, settings(), date(2026, 9, 9))

    assert before["depth_tracking_available"] is False
    assert after["depth_tracking_available"] is True
    payload = {
        "report_date": "2026-09-08",
        "channels": {
            "rsya": reports._with_starts(reports._summarize_direct([]), {}),
            "search": reports._with_starts(reports._summarize_direct([]), {}),
        },
        "comparison_previous": {
            "rsya": reports._with_starts(reports._summarize_direct([]), {}),
            "search": reports._with_starts(reports._summarize_direct([]), {}),
        },
        "internal": before,
    }
    before_cells = reports.render_rich_messages(payload)[3]["rich_message"]["blocks"][1]["cells"]
    assert before_cells[4][1]["text"] == "НД"
    payload["internal"] = after
    after_cells = reports.render_rich_messages(payload)[3]["rich_message"]["blocks"][1]["cells"]
    assert after_cells[4][1]["text"] == "0"


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
