import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.marketing_routes import router as marketing_router  # noqa: E402
from app.models import AttributionEvent, TelegramTrackingEvent, TelegramTrackingLink, User  # noqa: E402


get_settings.cache_clear()
app = FastAPI()
app.include_router(marketing_router)


def make_client() -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app, base_url="https://app.edabalans.ru"), factory


ADMIN_AUTH = ("admin@example.com", "test-admin-password")


def test_marketing_overview_builds_lead_funnel_and_campaign_breakdown() -> None:
    client, factory = make_client()
    occurred_at = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    with factory() as db:
        user = User(display_name="Лид", status="active")
        link = TelegramTrackingLink(
            id="link-1",
            platform="yandex",
            placement="rsya",
            campaign="707454796",
            name="Яндекс · подготовка",
            target_kind="bot_start",
            status="active",
        )
        db.add_all([user, link])
        db.flush()
        db.add_all(
            [
                TelegramTrackingEvent(
                    id="event-click",
                    tracking_link_id=link.id,
                    event_type="web_click",
                    metadata_json={"raw_query": {"utm_source": "attacker-value", "utm_campaign": "poisoned-campaign", "yclid": "secret-click-id"}},
                    occurred_at=occurred_at,
                ),
                TelegramTrackingEvent(
                    id="event-start-before-link",
                    tracking_link_id=link.id,
                    telegram_user_id="42",
                    event_type="start_maintenance",
                    metadata_json={},
                    occurred_at=occurred_at,
                ),
                TelegramTrackingEvent(
                    id="event-start",
                    tracking_link_id=link.id,
                    user_id=user.id,
                    telegram_user_id="42",
                    event_type="start_first",
                    metadata_json={},
                    occurred_at=occurred_at,
                ),
                TelegramTrackingEvent(
                    id="event-subscription",
                    user_id=user.id,
                    telegram_user_id="42",
                    event_type="subscription_check",
                    metadata_json={"subscribed": True},
                    occurred_at=occurred_at,
                ),
            ]
        )
        db.commit()

    assert client.get("/admin/api/marketing/overview").status_code == 401
    assert client.get("/admin/api/marketing/overview", auth=ADMIN_AUTH).status_code == 200
    response = client.get("/admin/api/marketing/overview?from=2025-12-01&to=2026-09-02", auth=ADMIN_AUTH)
    assert response.status_code == 200
    payload = response.json()
    stages = {stage["code"]: stage for stage in payload["stages"]}
    assert stages["web_click"]["count"] == 1
    assert stages["bot_start"]["count"] == 1
    assert stages["channel_subscribed"]["count"] == 1
    assert stages["intensive_day_1_open"]["status"] == "pending"
    assert stages["site_home_open"]["status"] == "pending"
    assert stages["intensive_later_open"]["status"] == "pending"
    assert {item["code"] for item in payload["missing_events"] if item["needed"]} == {
        "intensive_day_1_open",
        "site_home_open",
        "intensive_day_open",
    }
    assert payload["breakdown"][0]["campaign"] == "707454796"
    assert payload["breakdown"][0]["source"] == "yandex"
    assert payload["breakdown"][0]["placement"] == "rsya"
    assert payload["breakdown"][0]["bot_starts"] == 1
    assert payload["breakdown"][0]["subscribers"] == 1
    assert "secret-click-id" not in response.text


def test_marketing_period_starts_no_earlier_than_december_2025() -> None:
    client, _ = make_client()
    response = client.get("/admin/api/marketing/overview?from=2025-11-30&to=2026-01-01", auth=ADMIN_AUTH)
    assert response.status_code == 400
    assert "до декабря 2025" in response.json()["detail"]


def test_marketing_period_uses_inclusive_moscow_calendar_days() -> None:
    client, factory = make_client()
    with factory() as db:
        for event_id, occurred_at in (
            ("before", datetime(2025, 11, 30, 20, 59, tzinfo=timezone.utc)),
            ("start", datetime(2025, 11, 30, 21, 0, tzinfo=timezone.utc)),
            ("end", datetime(2025, 12, 1, 20, 59, tzinfo=timezone.utc)),
            ("after", datetime(2025, 12, 1, 21, 0, tzinfo=timezone.utc)),
        ):
            db.add(TelegramTrackingEvent(id=event_id, event_type="web_click", metadata_json={}, occurred_at=occurred_at))
        db.commit()
    response = client.get(
        "/admin/api/marketing/overview?from=2025-12-01&to=2025-12-01",
        auth=ADMIN_AUTH,
    )
    assert response.status_code == 200
    stages = {stage["code"]: stage for stage in response.json()["stages"]}
    assert stages["web_click"]["count"] == 2


def test_downstream_event_inherits_campaign_from_start_before_selected_period() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Лид", status="active")
        link = TelegramTrackingLink(id="link-old", platform="yandex", placement="rsya", campaign="campaign-old", name="Старая связка", target_kind="bot_start", status="active")
        db.add_all([user, link])
        db.flush()
        db.add_all([
            TelegramTrackingEvent(id="old-start", tracking_link_id=link.id, user_id=user.id, telegram_user_id="99", event_type="start_first", metadata_json={}, occurred_at=datetime(2025, 12, 10, tzinfo=timezone.utc)),
            TelegramTrackingEvent(id="current-repeat", user_id=user.id, telegram_user_id="99", event_type="start_repeat", metadata_json={}, occurred_at=datetime(2026, 2, 10, 8, 0, tzinfo=timezone.utc)),
            TelegramTrackingEvent(id="later-subscription", user_id=user.id, telegram_user_id="99", event_type="subscription_check", metadata_json={"subscribed": True}, occurred_at=datetime(2026, 2, 10, 9, 0, tzinfo=timezone.utc)),
        ])
        db.commit()
    response = client.get(
        "/admin/api/marketing/overview?from=2026-02-01&to=2026-02-28",
        auth=ADMIN_AUTH,
    )
    assert response.status_code == 200
    payload = response.json()
    stages = {stage["code"]: stage for stage in payload["stages"]}
    assert stages["bot_start"]["count"] == 1
    assert stages["channel_subscribed"]["count"] == 1
    assert payload["breakdown"][0]["campaign"] == "campaign-old"
    assert payload["breakdown"][0]["subscribers"] == 1


def test_start_before_period_is_attribution_history_not_current_cohort() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Старый лид", status="active")
        db.add(user)
        db.flush()
        db.add_all([
            TelegramTrackingEvent(id="history-only-start", user_id=user.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2025, 12, 15, 9, 0, tzinfo=timezone.utc)),
            TelegramTrackingEvent(id="current-subscription-only", user_id=user.id, event_type="subscription_check", metadata_json={"subscribed": True}, occurred_at=datetime(2026, 2, 15, 9, 0, tzinfo=timezone.utc)),
        ])
        db.commit()
    response = client.get("/admin/api/marketing/overview?from=2026-02-01&to=2026-02-28", auth=ADMIN_AUTH)
    payload = response.json()
    stages = {stage["code"]: stage for stage in payload["stages"]}
    assert stages["bot_start"]["count"] == 0
    assert stages["channel_subscribed"]["count"] == 0
    assert payload["breakdown"] == []


def test_funnel_only_counts_events_after_the_previous_known_stage(monkeypatch) -> None:
    monkeypatch.setenv("MARKETING_DAY_ONE_EVENTS_ENABLED", "true")
    get_settings.cache_clear()
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Лид", status="active")
        db.add(user)
        db.flush()
        db.add_all([
            TelegramTrackingEvent(id="day-before-start", user_id=user.id, event_type="intensive_day_1_open", metadata_json={}, occurred_at=datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)),
            TelegramTrackingEvent(id="start-after-day", user_id=user.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)),
            TelegramTrackingEvent(id="subscription-after-start", user_id=user.id, event_type="subscription_check", metadata_json={"subscribed": True}, occurred_at=datetime(2026, 1, 10, 11, 0, tzinfo=timezone.utc)),
        ])
        db.commit()
    response = client.get("/admin/api/marketing/overview?from=2026-01-10&to=2026-01-10", auth=ADMIN_AUTH)
    stages = {stage["code"]: stage for stage in response.json()["stages"]}
    assert stages["bot_start"]["count"] == 1
    assert stages["intensive_day_1_open"]["count"] == 0
    assert stages["channel_subscribed"]["count"] == 0
    payload = response.json()
    assert payload["breakdown"][0]["day_one_opens"] == 0
    assert payload["breakdown"][0]["subscribers"] == 0
    assert payload["day_opens"] == []
    get_settings.cache_clear()


def test_max_starts_are_read_from_shared_attribution_events() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="MAX-лид", status="active")
        db.add(user)
        db.flush()
        db.add_all([
            AttributionEvent(
                user_id=user.id,
                event_type="max_first_touch",
                source_raw="MAX · интенсив",
                utm_source="max",
                utm_medium="bot",
                utm_campaign="intensive",
                occurred_at=datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc),
            ),
            AttributionEvent(
                user_id=user.id,
                event_type="max_start_maintenance",
                source_raw="MAX · интенсив",
                occurred_at=datetime(2026, 1, 15, 9, 1, tzinfo=timezone.utc),
            ),
        ])
        db.commit()
    response = client.get("/admin/api/marketing/overview?from=2026-01-15&to=2026-01-15", auth=ADMIN_AUTH)
    payload = response.json()
    stages = {stage["code"]: stage for stage in payload["stages"]}
    assert stages["bot_start"]["count"] == 1
    assert payload["breakdown"][0]["source"] == "max"
    max_integration = next(item for item in payload["integrations"] if item["code"] == "max")
    assert max_integration["status"] == "collecting"


@pytest.mark.parametrize("event_type", ["max_first_touch", "max_start_maintenance", "max_start_unknown"])
def test_each_max_start_event_type_is_counted_on_its_own(event_type: str) -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Одиночный MAX-лид", status="active")
        db.add(user)
        db.flush()
        db.add(AttributionEvent(user_id=user.id, event_type=event_type, source_raw="MAX", utm_source="max", occurred_at=datetime(2026, 1, 16, 9, 0, tzinfo=timezone.utc)))
        db.commit()
    response = client.get("/admin/api/marketing/overview?from=2026-01-16&to=2026-01-16", auth=ADMIN_AUTH)
    stages = {stage["code"]: stage for stage in response.json()["stages"]}
    assert stages["bot_start"]["count"] == 1


def test_cross_platform_repeat_start_stays_in_one_first_touch_row() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Кросс-платформенный лид", status="active")
        telegram_link = TelegramTrackingLink(id="telegram-first", platform="telegram", placement="channel", campaign="first-touch", name="Первый вход", target_kind="bot_start", status="active")
        db.add_all([user, telegram_link])
        db.flush()
        db.add_all([
            TelegramTrackingEvent(id="telegram-start-old", tracking_link_id=telegram_link.id, user_id=user.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2025, 12, 20, 9, 0, tzinfo=timezone.utc)),
            AttributionEvent(user_id=user.id, event_type="max_first_touch", source_raw="MAX link", utm_source="max", utm_campaign="second-touch", occurred_at=datetime(2026, 1, 20, 9, 0, tzinfo=timezone.utc)),
            AttributionEvent(user_id=user.id, event_type="max_start_maintenance", source_raw="MAX link", occurred_at=datetime(2026, 1, 20, 9, 1, tzinfo=timezone.utc)),
        ])
        db.commit()
    response = client.get("/admin/api/marketing/overview?from=2026-01-20&to=2026-01-20", auth=ADMIN_AUTH)
    payload = response.json()
    rows_with_starts = [row for row in payload["breakdown"] if row["bot_starts"]]
    assert len(rows_with_starts) == 1
    assert rows_with_starts[0]["campaign"] == "first-touch"
    assert rows_with_starts[0]["bot_starts"] == 1


def test_first_touch_is_chronological_when_max_precedes_telegram() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="MAX был первым", status="active")
        telegram_link = TelegramTrackingLink(id="telegram-later", platform="telegram", placement="channel", campaign="later-touch", name="Повторный вход", target_kind="bot_start", status="active")
        db.add_all([user, telegram_link])
        db.flush()
        db.add_all([
            AttributionEvent(user_id=user.id, event_type="max_first_touch", source_raw="MAX first", utm_source="max", utm_campaign="first-touch", occurred_at=datetime(2025, 12, 19, 9, 0, tzinfo=timezone.utc)),
            TelegramTrackingEvent(id="telegram-start-later", tracking_link_id=telegram_link.id, user_id=user.id, event_type="start_repeat", metadata_json={}, occurred_at=datetime(2026, 1, 21, 9, 0, tzinfo=timezone.utc)),
        ])
        db.commit()
    response = client.get("/admin/api/marketing/overview?from=2026-01-21&to=2026-01-21", auth=ADMIN_AUTH)
    row = next(item for item in response.json()["breakdown"] if item["bot_starts"])
    assert row["source"] == "max"
    assert row["campaign"] == "first-touch"


def test_crm_merged_users_keep_one_path_and_campaign(monkeypatch) -> None:
    monkeypatch.setenv("MARKETING_DAY_ONE_EVENTS_ENABLED", "true")
    get_settings.cache_clear()
    client, factory = make_client()
    with factory() as db:
        canonical = User(display_name="Канонический", status="active")
        duplicate = User(display_name="Дубль", status="active")
        link = TelegramTrackingLink(id="merged-link", platform="yandex", placement="rsya", campaign="merged-campaign", name="Связка дубля", target_kind="bot_start", status="active")
        db.add_all([canonical, duplicate, link])
        db.flush()
        duplicate.merged_into_user_id = canonical.id
        db.add_all([
            TelegramTrackingEvent(id="duplicate-start", tracking_link_id=link.id, user_id=duplicate.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2026, 1, 20, 9, 0, tzinfo=timezone.utc)),
            TelegramTrackingEvent(id="canonical-repeat", user_id=canonical.id, event_type="start_repeat", metadata_json={}, occurred_at=datetime(2026, 1, 20, 10, 0, tzinfo=timezone.utc)),
            TelegramTrackingEvent(id="canonical-day-one", user_id=canonical.id, event_type="intensive_day_1_open", metadata_json={}, occurred_at=datetime(2026, 1, 20, 11, 0, tzinfo=timezone.utc)),
        ])
        db.commit()
    response = client.get("/admin/api/marketing/overview?from=2026-01-20&to=2026-01-20", auth=ADMIN_AUTH)
    payload = response.json()
    stages = {stage["code"]: stage for stage in payload["stages"]}
    assert stages["bot_start"]["count"] == 1
    assert stages["intensive_day_1_open"]["count"] == 1
    row = next(item for item in payload["breakdown"] if item["bot_starts"])
    assert row["campaign"] == "merged-campaign"
    assert row["day_one_opens"] == 1
    get_settings.cache_clear()


def test_later_days_require_home_and_match_all_views(monkeypatch) -> None:
    monkeypatch.setenv("MARKETING_DAY_ONE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("MARKETING_SITE_HOME_EVENTS_ENABLED", "true")
    monkeypatch.setenv("MARKETING_LATER_DAY_EVENTS_ENABLED", "true")
    get_settings.cache_clear()
    client, factory = make_client()
    with factory() as db:
        valid = User(display_name="Верный порядок", status="active")
        invalid = User(display_name="Неверный порядок", status="active")
        db.add_all([valid, invalid])
        db.flush()
        for prefix, user, later_hour, home_hour in (("valid", valid, 13, 12), ("invalid", invalid, 12, 13)):
            db.add_all([
                TelegramTrackingEvent(id=f"{prefix}-start", user_id=user.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2026, 1, 25, 9, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id=f"{prefix}-day-one", user_id=user.id, event_type="intensive_day_1_open", metadata_json={}, occurred_at=datetime(2026, 1, 25, 10, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id=f"{prefix}-subscription", user_id=user.id, event_type="subscription_check", metadata_json={"subscribed": True}, occurred_at=datetime(2026, 1, 25, 11, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id=f"{prefix}-home", user_id=user.id, event_type="site_home_open", metadata_json={}, occurred_at=datetime(2026, 1, 25, home_hour, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id=f"{prefix}-day-two", user_id=user.id, event_type="intensive_day_2_open", metadata_json={}, occurred_at=datetime(2026, 1, 25, later_hour, 0, tzinfo=timezone.utc)),
            ])
        db.commit()
    response = client.get("/admin/api/marketing/overview?from=2026-01-25&to=2026-01-25", auth=ADMIN_AUTH)
    payload = response.json()
    stages = {stage["code"]: stage for stage in payload["stages"]}
    assert stages["intensive_later_open"]["count"] == 1
    assert sum(row["later_day_users"] for row in payload["breakdown"]) == 1
    assert payload["day_opens"] == [{"day": 1, "users": 2}, {"day": 2, "users": 1}]
    get_settings.cache_clear()


def test_zero_is_not_reported_as_missing_when_event_producer_is_enabled(monkeypatch) -> None:
    monkeypatch.setenv("MARKETING_DAY_ONE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("MARKETING_SITE_HOME_EVENTS_ENABLED", "true")
    monkeypatch.setenv("MARKETING_LATER_DAY_EVENTS_ENABLED", "true")
    get_settings.cache_clear()
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Лид без первого дня", status="active")
        db.add(user)
        db.flush()
        db.add_all([
            TelegramTrackingEvent(id="enabled-start", user_id=user.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)),
            TelegramTrackingEvent(id="should-not-bypass-day-one", user_id=user.id, event_type="subscription_check", metadata_json={"subscribed": True}, occurred_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)),
            TelegramTrackingEvent(id="should-not-bypass-subscription", user_id=user.id, event_type="site_home_open", metadata_json={}, occurred_at=datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)),
        ])
        db.commit()
    response = client.get("/admin/api/marketing/overview?from=2026-01-01&to=2026-01-01", auth=ADMIN_AUTH)
    payload = response.json()
    stage = next(item for item in payload["stages"] if item["code"] == "intensive_day_1_open")
    subscription = next(item for item in payload["stages"] if item["code"] == "channel_subscribed")
    site_home = next(item for item in payload["stages"] if item["code"] == "site_home_open")
    later = next(item for item in payload["stages"] if item["code"] == "intensive_later_open")
    missing = next(item for item in payload["missing_events"] if item["code"] == "intensive_day_1_open")
    assert stage["status"] == "collecting"
    assert stage["count"] == 0
    assert subscription["count"] == 0
    assert site_home["count"] == 0
    assert later["status"] == "collecting"
    assert later["count"] == 0
    assert missing["needed"] is False
    assert next(item for item in payload["missing_events"] if item["code"] == "site_home_open")["needed"] is False
    assert next(item for item in payload["missing_events"] if item["code"] == "intensive_day_open")["needed"] is False
    get_settings.cache_clear()


def test_direct_oauth_token_never_appears_in_admin_response(monkeypatch) -> None:
    secret = "y0_private-direct-token"
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", secret)
    get_settings.cache_clear()
    client, _ = make_client()
    response = client.get("/admin/api/marketing/overview", auth=ADMIN_AUTH)
    assert response.status_code == 200
    assert secret not in response.text
    direct = next(item for item in response.json()["integrations"] if item["code"] == "yandex_direct")
    assert direct["status"] == "configured"
    get_settings.cache_clear()


def test_marketing_page_uses_protected_unified_admin_shell() -> None:
    client, _ = make_client()
    response = client.get("/admin/marketing", follow_redirects=False)
    assert response.status_code == 303
    response = client.get("/admin/marketing", auth=ADMIN_AUTH)
    assert response.status_code == 200
    assert 'id="admin-content"' in response.text
    assert "/admin/static/marketing.css" in response.text
