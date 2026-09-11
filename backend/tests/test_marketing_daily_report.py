import json
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
        {"Date": "2026-09-07", "CampaignId": "714157420", "AdGroupId": "1", "AdId": "1920472171246211821", "Device": "MOBILE", "Impressions": "1000", "Clicks": "100", "Sessions": "92", "Cost": "1000"},
        {"Date": "2026-09-07", "CampaignId": "714152601", "AdGroupId": "2", "AdId": "1920469239931549227", "Device": "DESKTOP", "Impressions": "100", "Clicks": "10", "Sessions": "9", "Cost": "500"},
        {"Date": "2026-09-06", "CampaignId": "714157420", "AdGroupId": "1", "AdId": "1920472171246211821", "Device": "MOBILE", "Impressions": "500", "Clicks": "50", "Sessions": "48", "Cost": "400"},
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
        "acquisition_page_depth": {"25": 4, "50": 3, "75": 2, "100": 1},
        "acquisition_video_depth": {"25": 3, "50": 2, "75": 1, "100": 1},
        "depth_tracking_available": True,
        "end_day_cta": 2,
        "acquisition_end_day_cta": 2,
        "subscribed": 1,
        "acquisition_subscribed": 1,
        "reminder_tracking_available": True,
        "acquisition_reminders_sent": 2,
        "acquisition_reminders_eligible_within_3h": 2,
        "acquisition_opened_within_3h_after_reminder": 1,
        "by_creative": {"control_cakes": 4, "1920469239931549227": 2},
        "by_messenger": {"tg": {"entries": 8, "starts": 5}, "max": {"entries": 4, "starts": 1}},
        "by_method": {"button": {"entries": 10, "starts": 5}, "qr": {"entries": 2, "starts": 1}},
        "by_device": {"mobile": {"entries": 10, "starts": 5}, "desktop": {"entries": 2, "starts": 1}},
    }


def test_report_compares_days_and_uses_real_internal_starts(monkeypatch):
    monkeypatch.setattr(reports, "_direct_report", lambda *_args, **_kwargs: direct_rows())
    monkeypatch.setattr(reports, "_direct_campaign_budgets", lambda *_args, **_kwargs: {714152601: 3500.0, 714157420: 10000.0})
    monkeypatch.setattr(reports, "_internal_snapshot", lambda *_args, **_kwargs: internal_snapshot())
    payload = reports.build_daily_report(None, settings(), date(2026, 9, 7))

    assert payload["channels"]["rsya"]["total"]["starts"] == 4
    assert payload["channels"]["search"]["total"]["starts"] == 2
    assert payload["comparison_previous"]["rsya"]["total"]["clicks"] == 50
    assert payload["cumulative"]["rsya"]["total"]["clicks"] == 0
    assert any("Start 4" in message for message in payload["telegram_messages"])
    assert all("АВТОРАЗБОР БЕЗ ИИ" not in message for message in payload["telegram_messages"])
    assert len(payload["telegram_messages"]) == 2
    assert payload["telegram_messages"][0].splitlines()[0] == "📊 РСЯ · 07.09.2026 00:00–08.09.2026 00:00 МСК"
    assert "🧭 ПУТЬ ЛИДА · входы и действия 07.09.2026 00:00–08.09.2026 00:00 МСК" in payload["telegram_messages"][0]
    assert len(payload["telegram_rich_messages"]) == 2
    assert payload["telegram_rich_messages"][0]["rich_message"]["blocks"][0]["text"] == "📊 РСЯ и путь лида · 07.09.2026"
    assert [message["fallback_text"] for message in payload["telegram_rich_messages"]] == payload["telegram_messages"]
    first_blocks = payload["telegram_rich_messages"][0]["rich_message"]["blocks"]
    rsya_table = next(block for block in first_blocks if block.get("type") == "table" and block.get("caption") == "РСЯ")
    assert [cell["text"] for cell in rsya_table["cells"][0]] == ["Вариант", "Пок.", "Кл.", "CTR", "Расход", "Start", "CPA"]
    assert rsya_table["cells"][1][0]["text"] == "ИТОГО"
    assert [row[0]["text"] for row in rsya_table["cells"][1:]] == [
        "ИТОГО", *[ad["name"] for ad in payload["channels"]["rsya"]["ads"]]
    ]
    funnel_table = next(block for block in first_blocks if block.get("type") == "table" and block.get("caption") == "Путь лида · РСЯ")
    assert [cell["text"] for cell in funnel_table["cells"][0]] == ["Этап", "Кол-во", "От шага", "От клика"]
    labels = [row[0]["text"] for row in funnel_table["cells"][1:]]
    assert labels == [
        "Клики рекламы", "Посетили посадку", "↳ Телефон", "↳ ПК", "Нажали кнопку мессенджера",
        "↳ MAX", "↳ Telegram", "↳ QR-код", "Нажали Start", "Открыли день 1", "↳ Напоминание",
        "↳ Полное окно ≤3ч", "↳ Открыли ≤3ч", "Текст 25%", "Текст 50%", "Текст 75%", "Текст 100%",
        "Видео старт", "Видео 25%", "Видео 50%", "Видео 75%", "Видео 100%",
        "Кнопка в конце", "Подписались",
    ]
    fallback = payload["telegram_messages"][0]
    assert "ИТОГО:" in fallback
    for ad in payload["channels"]["rsya"]["ads"]:
        assert ad["name"] in fallback
    for label in labels:
        assert f"{label}:" in fallback
    assert funnel_table["cells"][2][1]["text"] == "92"
    assert funnel_table["cells"][2][2]["text"] == "92.0%"
    assert funnel_table["cells"][14][1]["text"] == "4"
    assert funnel_table["cells"][23][0]["text"] == "Кнопка в конце"
    assert payload["channels"]["search"]["total"]["weekly_budget_rub"] == 3500.0
    assert payload["channels"]["search"]["total"]["week_remaining_rub"] == 3000.0
    footer = next(block for block in first_blocks if block.get("type") == "footer")
    assert "РСЯ: неделя 1 000 ₽ из 10 000 ₽ · осталось 9 000 ₽" in footer["text"]
    assert "demo_ai_message" not in payload
    assert len(payload["channels"]["rsya"]["ads"]) == 1
    assert len(payload["channels"]["search"]["ads"]) == 1
    assert "Видео 100%" in payload["telegram_messages"][0]
    assert "от шага" in payload["telegram_messages"][0]


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


def test_reminder_snapshot_counts_sent_and_opened_during_next_three_hours():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE tg_contacts (id TEXT PRIMARY KEY, user_id TEXT)")
        connection.exec_driver_sql("CREATE TABLE tg_sequence_runs (id TEXT PRIMARY KEY, contact_id TEXT)")
        connection.exec_driver_sql(
            "CREATE TABLE tg_step_deliveries (id TEXT PRIMARY KEY, run_id TEXT, step_key TEXT, status TEXT, sent_at TIMESTAMP)"
        )
        connection.exec_driver_sql("INSERT INTO tg_contacts VALUES ('c1', 'u1'), ('c2', 'u2')")
        connection.exec_driver_sql("INSERT INTO tg_sequence_runs VALUES ('r1', 'c1'), ('r2', 'c2')")
        connection.exec_driver_sql(
            "INSERT INTO tg_step_deliveries VALUES "
            "('d1', 'r1', 'welcome_reminder_day1', 'sent', '2026-09-07 09:15:00'), "
            "('d2', 'r2', 'welcome_reminder_day1', 'sent', '2026-09-07 09:20:00')"
        )
    starts = [
        {"user_id": "u1", "start": {"at": "2026-09-07T09:00:00+00:00"}, "day_one": {"at": "2026-09-07T11:00:00+00:00"}},
        {"user_id": "u2", "start": {"at": "2026-09-07T09:00:00+00:00"}, "day_one": {"at": "2026-09-07T13:00:00+00:00"}},
    ]
    with Session(engine) as db:
        result = reports._reminder_snapshot(db, starts, datetime(2026, 9, 8, tzinfo=timezone.utc))

    assert result == {"available": True, "sent": 2, "eligible_within_3h": 2, "opened_within_3h": 1}


def test_reminder_snapshot_does_not_count_open_after_report_cutoff():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE tg_contacts (id TEXT PRIMARY KEY, user_id TEXT)")
        connection.exec_driver_sql("CREATE TABLE tg_sequence_runs (id TEXT PRIMARY KEY, contact_id TEXT)")
        connection.exec_driver_sql(
            "CREATE TABLE tg_step_deliveries (id TEXT PRIMARY KEY, run_id TEXT, step_key TEXT, status TEXT, sent_at TIMESTAMP)"
        )
        connection.exec_driver_sql("INSERT INTO tg_contacts VALUES ('c1', 'u1')")
        connection.exec_driver_sql("INSERT INTO tg_sequence_runs VALUES ('r1', 'c1')")
        connection.exec_driver_sql(
            "INSERT INTO tg_step_deliveries VALUES "
            "('d1', 'r1', 'welcome_reminder_day1', 'sent', '2026-09-08 23:50:00')"
        )
    starts = [{
        "user_id": "u1",
        "start": {"at": "2026-09-08T23:30:00+00:00"},
        "day_one": {"at": "2026-09-09T00:10:00+00:00"},
    }]
    with Session(engine) as db:
        result = reports._reminder_snapshot(db, starts, datetime(2026, 9, 9, tzinfo=timezone.utc))

    assert result == {"available": True, "sent": 1, "eligible_within_3h": 0, "opened_within_3h": 0}


def test_weekly_spend_limit_is_read_from_active_nested_strategy():
    assert reports._weekly_spend_limit({
        "BiddingStrategy": {
            "Search": {"WbMaximumClicks": {"WeeklySpendLimit": 3_500_000_000}},
            "Network": {"BiddingStrategyType": "SERVING_OFF"},
        }
    }) == 3500.0


def test_direct_campaign_budgets_requests_and_maps_both_campaigns(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "result": {
                    "Campaigns": [
                        {
                            "Id": 714152601,
                            "TextCampaign": {"BiddingStrategy": {"Search": {"WbMaximumClicks": {"WeeklySpendLimit": 3_500_000_000}}}},
                        },
                        {
                            "Id": 714157420,
                            "TextCampaign": {"BiddingStrategy": {"Network": {"WbMaximumConversionRate": {"WeeklySpendLimit": 10_000_000_000}}}},
                        },
                    ]
                }
            }).encode("utf-8")

    def urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(reports.urllib.request, "urlopen", urlopen)
    result = reports._direct_campaign_budgets(settings(), [714152601, 714157420])

    assert captured["url"] == reports.DIRECT_CAMPAIGNS_URL
    assert captured["body"]["params"]["SelectionCriteria"]["Ids"] == [714152601, 714157420]
    assert captured["body"]["params"]["TextCampaignFieldNames"] == ["BiddingStrategy"]
    assert captured["timeout"] == 30
    assert result == {714152601: 3500.0, 714157420: 10000.0}


def test_missing_sessions_is_no_data_instead_of_zero_or_error():
    rows = [{
        "Date": "2026-09-07", "CampaignId": "714157420", "AdGroupId": "1",
        "AdId": "1920472171246211821", "Device": "MOBILE", "Impressions": "100",
        "Clicks": "10", "Sessions": "--", "Cost": "100",
    }]
    rsya = reports._with_starts(reports._summarize_direct(rows), {})
    search = reports._with_starts(reports._summarize_direct([]), {})
    payload = {
        "report_date": "2026-09-07",
        "channels": {"rsya": rsya, "search": search},
        "comparison_previous": {"rsya": reports._with_starts(reports._summarize_direct([]), {}), "search": search},
        "internal": internal_snapshot(),
    }

    assert rsya["total"]["sessions_available"] is False
    cells = next(
        block for block in reports.render_rich_messages(payload)[0]["rich_message"]["blocks"]
            if block.get("type") == "table" and block.get("caption") == "Путь лида · РСЯ"
    )["cells"]
    assert cells[2][0]["text"] == "Посетили посадку"
    assert cells[2][1]["text"] == "НД"
    assert cells[3][1]["text"] == "НД"
    assert cells[4][1]["text"] == "НД"


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
    funnel_cells = next(block for block in rich[0]["rich_message"]["blocks"] if block.get("type") == "table" and block.get("caption") == "Путь лида · РСЯ")["cells"]
    assert funnel_cells[5][1]["text"] == "НД"
    assert funnel_cells[6][1]["text"] == "НД"
    assert funnel_cells[7][1]["text"] == "НД"


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
        "start": {"at": "2026-09-09T00:01:00+03:00"},
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
    assert result["acquisition_starts"] == 1
    assert result["entries"] == 3
    assert result["by_creative"] == {"control_cakes": 1}
    assert result["by_method"]["button"] == {"entries": 3, "starts": 1}


def test_acquisition_cohort_drives_reminder_subscription_and_funnel_rows(monkeypatch):
    report_day = date(2026, 9, 8)
    attributed = {
        "user_id": str(uuid4()),
        "journey_id": "journey-attributed",
        "source": "Яндекс",
        "is_new_lead": True,
        "creative": "control_cakes",
        "messenger": "tg",
        "entry_method": "button",
        "device": "mobile",
        "landing_entry": {"at": "2026-09-08T18:00:00+03:00", "method": "button"},
        "start": {"at": "2026-09-08T18:01:00+03:00"},
        "day_one": {"at": "2026-09-08T18:02:00+03:00"},
        "subscription": {"at": "2026-09-08T19:00:00+03:00"},
        "other_actions": [{"label": "Нажал Telegram в интенсиве", "at": "2026-09-08T18:55:00+03:00"}],
    }
    organic = {
        **attributed,
        "user_id": str(uuid4()),
        "journey_id": "journey-organic",
        "source": "Telegram",
        "landing_entry": None,
    }

    def dashboard(*_args, **kwargs):
        if kwargs["date_from"] == report_day:
            return {
                "rows": [attributed],
                "entry_breakdown": [{"source": "Яндекс", "messenger": "tg", "entry": "button", "entries": 1}],
            }
        return {"rows": [attributed, organic], "entry_breakdown": []}

    reminder_cohorts = []
    monkeypatch.setattr(reports, "marketing_dashboard", dashboard)
    monkeypatch.setattr(
        reports,
        "_course_depth_snapshot",
        lambda _db, starts, _cutoff: {
            "page": {"25": len(starts), "50": 0, "75": 0, "100": 0},
            "video": {"25": 0, "50": 0, "75": 0, "100": 0},
        },
    )

    def reminder(_db, starts, _cutoff):
        reminder_cohorts.append(starts)
        return {"available": True, "sent": 1, "opened_within_3h": 1}

    monkeypatch.setattr(reports, "_reminder_snapshot", reminder)
    result = reports._internal_snapshot(None, settings(), report_day)

    assert [row["journey_id"] for row in reminder_cohorts[0]] == ["journey-attributed"]
    assert result["acquisition_reminders_sent"] == 1
    assert result["acquisition_opened_within_3h_after_reminder"] == 1
    assert result["acquisition_subscribed"] == 1

    payload = {
        "report_date": report_day.isoformat(),
        "channels": {
            "rsya": reports._with_starts(reports._summarize_direct([direct_rows()[0]]), {"control_cakes": 1}),
            "search": reports._with_starts(reports._summarize_direct([]), {}),
        },
        "comparison_previous": {
            "rsya": reports._with_starts(reports._summarize_direct([]), {}),
            "search": reports._with_starts(reports._summarize_direct([]), {}),
        },
        "internal": result,
    }
    cells = next(
        block for block in reports.render_rich_messages(payload)[0]["rich_message"]["blocks"]
            if block.get("type") == "table" and block.get("caption") == "Путь лида · РСЯ"
    )["cells"]
    rows_by_label = {row[0]["text"]: row for row in cells[1:]}
    assert [cell["text"] for cell in rows_by_label["↳ Напоминание"][1:]] == ["1", "100.0%", "1.0%"]
    assert [cell["text"] for cell in rows_by_label["↳ Открыли ≤3ч"][1:]] == ["1", "100.0%", "1.0%"]
    assert [cell["text"] for cell in rows_by_label["Подписались"][1:]] == ["1", "100.0%", "1.0%"]


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
    before_cells = next(block for block in reports.render_rich_messages(payload)[0]["rich_message"]["blocks"] if block.get("type") == "table" and block.get("caption") == "Путь лида · РСЯ")["cells"]
    assert before_cells[14][1]["text"] == "НД"
    payload["internal"] = after
    after_cells = next(block for block in reports.render_rich_messages(payload)[0]["rich_message"]["blocks"] if block.get("type") == "table" and block.get("caption") == "Путь лида · РСЯ")["cells"]
    assert after_cells[14][1]["text"] == "0"


def test_rsya_and_search_funnels_do_not_mix_messenger_entries_or_starts():
    empty = reports._with_starts(reports._summarize_direct([]), {})
    payload = {
        "report_date": "2026-09-08",
        "channels": {"rsya": empty, "search": reports._with_starts(reports._summarize_direct([]), {})},
        "comparison_previous": {"rsya": reports._with_starts(reports._summarize_direct([]), {}), "search": reports._with_starts(reports._summarize_direct([]), {})},
        "internal": {
            "entry_tracking_available": True,
            "depth_tracking_available": True,
            "reminder_tracking_available": True,
            "channels": {
                "rsya": {
                    "entries": 4, "acquisition_starts": 3, "acquisition_day_one": 0,
                    "acquisition_reminders_sent": 0, "acquisition_reminders_eligible_within_3h": 0,
                    "acquisition_opened_within_3h_after_reminder": 0,
                    "acquisition_page_depth": {}, "acquisition_video_depth": {}, "acquisition_video_engaged": 0,
                    "acquisition_end_day_cta": 0, "acquisition_subscribed": 0,
                    "by_messenger": {"max": {"entries": 3, "starts": 2}, "tg": {"entries": 1, "starts": 1}},
                    "by_method": {"button": {"entries": 4, "starts": 3}}, "by_device": {}, "tracking_errors": [],
                },
                "search": {
                    "entries": 2, "acquisition_starts": 1, "acquisition_day_one": 0,
                    "acquisition_reminders_sent": 0, "acquisition_reminders_eligible_within_3h": 0,
                    "acquisition_opened_within_3h_after_reminder": 0,
                    "acquisition_page_depth": {}, "acquisition_video_depth": {}, "acquisition_video_engaged": 0,
                    "acquisition_end_day_cta": 0, "acquisition_subscribed": 0,
                    "by_messenger": {"telegram": {"entries": 2, "starts": 1}},
                    "by_method": {"button": {"entries": 2, "starts": 1}}, "by_device": {}, "tracking_errors": [],
                },
            },
        },
    }

    rsya = reports._funnel_values(payload, "rsya")
    search = reports._funnel_values(payload, "search")

    assert (rsya["max"], rsya["max_starts"], rsya["telegram"], rsya["telegram_starts"]) == (3, 2, 1, 1)
    assert (search["max"], search["max_starts"], search["telegram"], search["telegram_starts"]) == (0, 0, 2, 1)


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
