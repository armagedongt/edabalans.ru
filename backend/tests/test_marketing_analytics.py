import os
from datetime import datetime, timezone
from pathlib import Path

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
from app import marketing_service  # noqa: E402
from app.marketing_routes import router as marketing_router  # noqa: E402
from app.models import (  # noqa: E402
    AttributionEvent,
    MessengerAccount,
    TelegramTrackingEvent,
    TelegramTrackingLink,
    User,
)


get_settings.cache_clear()
app = FastAPI()
app.include_router(marketing_router)
ADMIN_AUTH = ("admin@example.com", "test-admin-password")


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


def seed_full_path(factory: sessionmaker) -> None:
    with factory() as db:
        user = User(display_name="Сергей Тестовый", status="active")
        link = TelegramTrackingLink(
            id="pikabu-link",
            platform="Пикабу",
            placement="Пост · Висцеральный жир",
            campaign="Интенсив декабрь",
            name="Пикабу · Висцеральный жир",
            target_kind="bot_start",
            status="active",
        )
        db.add_all([user, link])
        db.flush()
        db.add(
            MessengerAccount(
                user_id=user.id,
                platform="telegram",
                platform_user_id="42",
                username="sergey_test",
                first_name="Сергей",
                source="telegram_bot",
            )
        )
        moments = {
            "click": datetime(2026, 1, 10, 8, 59, tzinfo=timezone.utc),
            "start": datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc),
            "before": datetime(2026, 1, 10, 9, 5, tzinfo=timezone.utc),
            "day1": datetime(2026, 1, 10, 9, 10, tzinfo=timezone.utc),
            "after": datetime(2026, 1, 10, 9, 20, tzinfo=timezone.utc),
            "home": datetime(2026, 1, 10, 9, 30, tzinfo=timezone.utc),
            "day2": datetime(2026, 1, 10, 9, 40, tzinfo=timezone.utc),
            "other": datetime(2026, 1, 10, 9, 45, tzinfo=timezone.utc),
        }
        db.add_all(
            [
                TelegramTrackingEvent(
                    id="click",
                    tracking_link_id=link.id,
                    event_type="web_click",
                    metadata_json={"raw_query": {"yclid": "never-return-this", "utm_source": "poisoned"}},
                    occurred_at=moments["click"],
                ),
                TelegramTrackingEvent(
                    id="start",
                    tracking_link_id=link.id,
                    user_id=user.id,
                    telegram_user_id="42",
                    event_type="start_first",
                    metadata_json={},
                    occurred_at=moments["start"],
                ),
                TelegramTrackingEvent(
                    id="check-before",
                    user_id=user.id,
                    telegram_user_id="42",
                    event_type="subscription_check",
                    metadata_json={"stage": "before_day1", "outcome": "not_checked_placeholder"},
                    occurred_at=moments["before"],
                ),
                TelegramTrackingEvent(
                    id="day-one",
                    user_id=user.id,
                    event_type="intensive_day_1_open",
                    metadata_json={},
                    occurred_at=moments["day1"],
                ),
                TelegramTrackingEvent(
                    id="check-after",
                    user_id=user.id,
                    event_type="subscription_check",
                    metadata_json={"stage": "after_day1", "outcome": "already_subscribed", "subscribed": True},
                    occurred_at=moments["after"],
                ),
                TelegramTrackingEvent(
                    id="home",
                    user_id=user.id,
                    event_type="site_home_open",
                    metadata_json={},
                    occurred_at=moments["home"],
                ),
                TelegramTrackingEvent(
                    id="day-two",
                    user_id=user.id,
                    event_type="intensive_day_2_open",
                    metadata_json={},
                    occurred_at=moments["day2"],
                ),
                TelegramTrackingEvent(
                    id="maintenance",
                    user_id=user.id,
                    event_type="maintenance_contact",
                    metadata_json={},
                    occurred_at=moments["other"],
                ),
            ]
        )
        db.commit()


def test_marketing_table_returns_user_and_complete_action_path(monkeypatch) -> None:
    monkeypatch.setenv("MARKETING_DAY_ONE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("MARKETING_SITE_HOME_EVENTS_ENABLED", "true")
    monkeypatch.setenv("MARKETING_LATER_DAY_EVENTS_ENABLED", "true")
    get_settings.cache_clear()
    client, factory = make_client()
    seed_full_path(factory)

    assert client.get("/admin/api/marketing/overview").status_code == 401
    response = client.get(
        "/admin/api/marketing/overview?from=2026-01-10&to=2026-01-10",
        auth=ADMIN_AUTH,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["totals"]["rows"] == 1
    row = payload["rows"][0]
    assert row["display_name"] == "Сергей Тестовый"
    assert row["usernames"] == ["@sergey_test"]
    assert row["source"] == "Пикабу"
    assert row["campaign"] == "Интенсив декабрь"
    assert row["start"]["label"] == "Первый старт бота"
    assert row["check_before_day_one"][0]["detail"] == "проверка ещё не выполнялась"
    assert row["day_one"] is not None
    assert row["subscription"]["detail"] == "уже подписан"
    assert row["check_after_day_one"]
    assert row["site_home"] is not None
    assert row["later_days"]["max_day"] == 2
    assert row["other_actions"][0]["label"] == "Действие в техническом режиме"
    assert row["last_action"]["label"] == "Действие в техническом режиме"
    metrics = {item["code"]: item for item in payload["analytics"]}
    assert metrics["web_click"]["count"] == 1
    assert metrics["bot_start"]["count"] == 1
    assert metrics["day_one"]["conversion_from_start"] == 100.0
    assert metrics["later_days"]["conversion_from_start"] == 100.0
    assert "never-return-this" not in response.text
    get_settings.cache_clear()


def test_filters_cover_source_campaign_user_and_all_sources() -> None:
    client, factory = make_client()
    seed_full_path(factory)
    with factory() as db:
        yandex_user = User(display_name="Яндекс-лид", status="active")
        yandex_link = TelegramTrackingLink(
            id="yandex-link",
            platform="Yandex Direct",
            placement="РСЯ",
            campaign="Новая кампания",
            name="Яндекс · новая",
            target_kind="bot_start",
            status="active",
        )
        db.add_all([yandex_user, yandex_link])
        db.flush()
        db.add(
            TelegramTrackingEvent(
                id="yandex-start",
                tracking_link_id=yandex_link.id,
                user_id=yandex_user.id,
                event_type="start_first",
                metadata_json={},
                occurred_at=datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc),
            )
        )
        db.add(
            TelegramTrackingEvent(
                id="yandex-click",
                tracking_link_id=yandex_link.id,
                event_type="web_click",
                metadata_json={},
                occurred_at=datetime(2026, 1, 10, 9, 55, tzinfo=timezone.utc),
            )
        )
        db.commit()
    base = "/admin/api/marketing/overview?from=2026-01-10&to=2026-01-10"

    payload = client.get(base, auth=ADMIN_AUTH).json()
    assert {"Яндекс", "Пикабу", "Telegram", "MAX", "Не определён"} <= set(payload["filters"]["sources"])
    assert payload["totals"]["rows"] == 2
    pikabu = client.get(f"{base}&source=Пикабу", auth=ADMIN_AUTH).json()
    assert pikabu["totals"]["rows"] == 1
    assert {item["code"]: item["count"] for item in pikabu["analytics"]}["day_one"] == 1
    yandex = client.get(f"{base}&source=Яндекс", auth=ADMIN_AUTH).json()
    assert yandex["totals"]["rows"] == 1
    assert yandex["rows"][0]["display_name"] == "Яндекс-лид"
    assert {item["code"]: item["count"] for item in yandex["analytics"]}["web_click"] == 1
    campaign = client.get(f"{base}&campaign=декабрь", auth=ADMIN_AUTH).json()
    assert campaign["totals"]["rows"] == 1
    assert campaign["rows"][0]["campaign"] == "Интенсив декабрь"
    assert {item["code"]: item["count"] for item in campaign["analytics"]}["web_click"] == 1
    searched = client.get(f"{base}&user=sergey_test", auth=ADMIN_AUTH).json()
    assert searched["totals"]["rows"] == 1
    assert {item["code"]: item["count"] for item in searched["analytics"]}["bot_start"] == 1
    missing = client.get(f"{base}&user=другой", auth=ADMIN_AUTH).json()
    assert missing["totals"]["rows"] == 0
    assert missing["totals"]["clicks_ignore_user_filter"] is True


def test_repeat_start_keeps_first_known_source_and_skips_initial_unknown() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Возвратный лид", status="active")
        pikabu = TelegramTrackingLink(id="repeat-pikabu", platform="Пикабу", placement="Пост", campaign="Первая", name="Первая ссылка", target_kind="bot_start", status="active")
        yandex = TelegramTrackingLink(id="repeat-yandex", platform="Яндекс", placement="РСЯ", campaign="Вторая", name="Вторая ссылка", target_kind="bot_start", status="active")
        db.add_all([user, pikabu, yandex])
        db.flush()
        db.add_all(
            [
                TelegramTrackingEvent(id="unknown-dec", user_id=user.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2025, 12, 2, 9, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="known-pikabu", user_id=user.id, tracking_link_id=pikabu.id, event_type="start_repeat", metadata_json={}, occurred_at=datetime(2025, 12, 3, 9, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="current-yandex", user_id=user.id, tracking_link_id=yandex.id, event_type="start_repeat", metadata_json={}, occurred_at=datetime(2026, 1, 20, 9, 0, tzinfo=timezone.utc)),
            ]
        )
        db.commit()
    payload = client.get("/admin/api/marketing/overview?from=2026-01-20&to=2026-01-20", auth=ADMIN_AUTH).json()
    assert payload["rows"][0]["source"] == "Пикабу"
    assert payload["rows"][0]["campaign"] == "Первая"


def test_first_known_source_is_stable_across_max_and_telegram() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Кроссплатформенный лид", status="active")
        telegram_link = TelegramTrackingLink(id="cross-telegram", platform="Telegram", placement="Канал", campaign="Telegram later", name="Поздняя ссылка", target_kind="bot_start", status="active")
        db.add_all([user, telegram_link])
        db.flush()
        db.add_all(
            [
                AttributionEvent(user_id=user.id, event_type="max_first_touch", source_raw="MAX · пост", utm_source="max", utm_campaign="MAX first", occurred_at=datetime(2025, 12, 5, 9, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="cross-current", user_id=user.id, tracking_link_id=telegram_link.id, event_type="start_repeat", metadata_json={}, occurred_at=datetime(2026, 1, 20, 9, 0, tzinfo=timezone.utc)),
            ]
        )
        db.commit()
    payload = client.get("/admin/api/marketing/overview?from=2026-01-20&to=2026-01-20", auth=ADMIN_AUTH).json()
    assert payload["rows"][0]["source"] == "MAX"
    assert payload["rows"][0]["campaign"] == "MAX first"


def test_retry_check_stays_before_day_one_and_join_request_is_not_subscription() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Ожидает вступления", status="active")
        db.add(user)
        db.flush()
        db.add_all(
            [
                TelegramTrackingEvent(id="retry-start", user_id=user.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2026, 1, 21, 9, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="retry-before", user_id=user.id, event_type="subscription_check", metadata_json={"stage": "before_day1", "outcome": "not_subscribed_initially"}, occurred_at=datetime(2026, 1, 21, 9, 4, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="retry-check", user_id=user.id, event_type="subscription_check", metadata_json={"stage": "after_prompt", "outcome": "not_subscribed_after_prompt"}, occurred_at=datetime(2026, 1, 21, 9, 5, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="join-request", user_id=user.id, event_type="channel_join_request", metadata_json={}, occurred_at=datetime(2026, 1, 21, 9, 6, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="retry-day-one", user_id=user.id, event_type="intensive_day_1_open", metadata_json={}, occurred_at=datetime(2026, 1, 21, 9, 10, tzinfo=timezone.utc)),
            ]
        )
        db.commit()
    payload = client.get("/admin/api/marketing/overview?from=2026-01-21&to=2026-01-21", auth=ADMIN_AUTH).json()
    row = payload["rows"][0]
    assert [item["detail"] for item in row["check_before_day_one"]] == ["не подписан", "не подписался после предложения"]
    assert row["check_after_day_one"] == []
    assert row["subscription"] is None
    assert [item["label"] for item in row["other_actions"]] == ["Отправил заявку в канал"]
    assert {item["code"]: item["count"] for item in payload["analytics"]}["subscribed"] == 0


def test_later_check_without_day_one_stays_after_and_channel_join_confirms_subscription() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Подписанный", status="active")
        db.add(user)
        db.flush()
        db.add_all(
            [
                TelegramTrackingEvent(id="join-start", user_id=user.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2026, 1, 22, 9, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="late-check", user_id=user.id, event_type="subscription_check", metadata_json={"stage": "after_day2", "outcome": "not_subscribed_at_check"}, occurred_at=datetime(2026, 1, 22, 9, 5, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="joined", user_id=user.id, event_type="channel_join", metadata_json={}, occurred_at=datetime(2026, 1, 22, 9, 6, tzinfo=timezone.utc)),
            ]
        )
        db.commit()
    payload = client.get("/admin/api/marketing/overview?from=2026-01-22&to=2026-01-22", auth=ADMIN_AUTH).json()
    row = payload["rows"][0]
    assert row["check_before_day_one"] == []
    assert row["check_after_day_one"][0]["detail"] == "не подписан"
    assert row["subscription"]["detail"] == "Вступил в канал"


def test_start_before_period_is_not_a_row_in_selected_date() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Старый лид", status="active")
        db.add(user)
        db.flush()
        db.add_all(
            [
                TelegramTrackingEvent(
                    id="old-start",
                    user_id=user.id,
                    event_type="start_first",
                    metadata_json={},
                    occurred_at=datetime(2025, 12, 10, 9, 0, tzinfo=timezone.utc),
                ),
                TelegramTrackingEvent(
                    id="new-check",
                    user_id=user.id,
                    event_type="subscription_check",
                    metadata_json={"subscribed": True},
                    occurred_at=datetime(2026, 2, 10, 9, 0, tzinfo=timezone.utc),
                ),
            ]
        )
        db.commit()
    payload = client.get(
        "/admin/api/marketing/overview?from=2026-02-01&to=2026-02-28",
        auth=ADMIN_AUTH,
    ).json()
    assert payload["rows"] == []


def test_merged_crm_users_share_one_row_and_canonical_name() -> None:
    client, factory = make_client()
    with factory() as db:
        canonical = User(display_name="Главная карточка", status="active")
        duplicate = User(display_name="Дубль", status="active")
        db.add_all([canonical, duplicate])
        db.flush()
        duplicate.merged_into_user_id = canonical.id
        db.add_all(
            [
                TelegramTrackingEvent(id="duplicate-start", user_id=duplicate.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2026, 1, 20, 9, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="canonical-repeat", user_id=canonical.id, event_type="start_repeat", metadata_json={}, occurred_at=datetime(2026, 1, 20, 10, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="canonical-day-one", user_id=canonical.id, event_type="intensive_day_1_open", metadata_json={}, occurred_at=datetime(2026, 1, 20, 11, 0, tzinfo=timezone.utc)),
            ]
        )
        db.commit()
    payload = client.get(
        "/admin/api/marketing/overview?from=2026-01-20&to=2026-01-20",
        auth=ADMIN_AUTH,
    ).json()
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["display_name"] == "Главная карточка"
    assert payload["rows"][0]["day_one"] is not None


def test_max_start_appears_as_user_row() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="MAX-лид", status="active")
        db.add(user)
        db.flush()
        db.add(
            AttributionEvent(
                user_id=user.id,
                event_type="max_first_touch",
                source_raw="MAX · интенсив",
                utm_source="max",
                utm_campaign="max-campaign",
                occurred_at=datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc),
            )
        )
        db.commit()
    payload = client.get(
        "/admin/api/marketing/overview?from=2026-01-15&to=2026-01-15&source=MAX",
        auth=ADMIN_AUTH,
    ).json()
    assert payload["totals"]["rows"] == 1
    assert payload["rows"][0]["source"] == "MAX"
    assert payload["rows"][0]["campaign"] == "max-campaign"


def test_period_uses_moscow_day_and_rejects_pre_december() -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Граница дня", status="active")
        db.add(user)
        db.flush()
        db.add_all(
            [
                TelegramTrackingEvent(id="before", user_id=user.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2025, 11, 30, 20, 59, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="pre-start-check", user_id=user.id, event_type="subscription_check", metadata_json={"subscribed": True}, occurred_at=datetime(2025, 11, 30, 21, 0, 30, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="inside", user_id=user.id, event_type="start_repeat", metadata_json={}, occurred_at=datetime(2025, 11, 30, 21, 1, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="after-period", user_id=user.id, event_type="subscription_check", metadata_json={"subscribed": True}, occurred_at=datetime(2025, 12, 1, 21, 0, tzinfo=timezone.utc)),
            ]
        )
        db.commit()
    payload = client.get(
        "/admin/api/marketing/overview?from=2025-12-01&to=2025-12-01",
        auth=ADMIN_AUTH,
    ).json()
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["subscription"] is None
    rejected = client.get(
        "/admin/api/marketing/overview?from=2025-11-30&to=2025-12-01",
        auth=ADMIN_AUTH,
    )
    assert rejected.status_code == 400


def test_analytics_use_all_matching_rows_when_visible_table_is_limited(monkeypatch) -> None:
    monkeypatch.setattr(marketing_service, "ROW_LIMIT", 1)
    client, factory = make_client()
    with factory() as db:
        first = User(display_name="Первый", status="active")
        second = User(display_name="Второй", status="active")
        db.add_all([first, second])
        db.flush()
        db.add_all(
            [
                TelegramTrackingEvent(id="limited-one", user_id=first.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2026, 1, 25, 9, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="limited-two", user_id=second.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2026, 1, 25, 10, 0, tzinfo=timezone.utc)),
            ]
        )
        db.commit()
    payload = client.get("/admin/api/marketing/overview?from=2026-01-25&to=2026-01-25", auth=ADMIN_AUTH).json()
    assert payload["totals"]["rows"] == 1
    assert payload["totals"]["matching_rows"] == 2
    assert {item["code"]: item["count"] for item in payload["analytics"]}["bot_start"] == 2


def test_optional_stage_collection_distinguishes_disconnected_from_zero(monkeypatch) -> None:
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Только старт", status="active")
        db.add(user)
        db.flush()
        db.add(TelegramTrackingEvent(id="only-start", user_id=user.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2026, 1, 26, 9, 0, tzinfo=timezone.utc)))
        db.commit()
    url = "/admin/api/marketing/overview?from=2026-01-26&to=2026-01-26"
    disconnected = client.get(url, auth=ADMIN_AUTH).json()
    assert disconnected["collection"] == {"day_one": False, "site_home": False, "later_days": False}
    assert {item["code"]: item["collection"] for item in disconnected["analytics"]}["day_one"] == "not_connected"

    monkeypatch.setenv("MARKETING_DAY_ONE_EVENTS_ENABLED", "true")
    get_settings.cache_clear()
    connected = client.get(url, auth=ADMIN_AUTH).json()
    assert connected["collection"]["day_one"] is True
    day_one = {item["code"]: item for item in connected["analytics"]}["day_one"]
    assert day_one["collection"] == "collecting"
    assert day_one["count"] == 0
    get_settings.cache_clear()


def test_event_safety_limit_is_disclosed(monkeypatch) -> None:
    monkeypatch.setattr(marketing_service, "EVENT_LIMIT", 1)
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Большая история", status="active")
        db.add(user)
        db.flush()
        db.add_all(
            [
                TelegramTrackingEvent(id="cap-start", user_id=user.id, event_type="start_first", metadata_json={}, occurred_at=datetime(2026, 1, 27, 9, 0, tzinfo=timezone.utc)),
                TelegramTrackingEvent(id="cap-repeat", user_id=user.id, event_type="start_repeat", metadata_json={}, occurred_at=datetime(2026, 1, 27, 10, 0, tzinfo=timezone.utc)),
            ]
        )
        db.commit()
    payload = client.get("/admin/api/marketing/overview?from=2026-01-27&to=2026-01-27", auth=ADMIN_AUTH).json()
    assert payload["totals"]["events_truncated"] is True
    script = (Path(__file__).parents[1] / "app" / "static" / "admin.js").read_text(encoding="utf-8")
    assert "Событий больше безопасного предела отчёта" in script


def test_direct_token_never_appears_in_table_response(monkeypatch) -> None:
    secret = "y0_private-direct-token"
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", secret)
    get_settings.cache_clear()
    client, _ = make_client()
    response = client.get("/admin/api/marketing/overview", auth=ADMIN_AUTH)
    assert response.status_code == 200
    assert secret not in response.text
    get_settings.cache_clear()


def test_marketing_page_uses_protected_unified_admin_shell() -> None:
    client, _ = make_client()
    response = client.get("/admin/marketing", follow_redirects=False)
    assert response.status_code == 303
    response = client.get("/admin/marketing", auth=ADMIN_AUTH)
    assert response.status_code == 200
    assert 'id="admin-content"' in response.text
    assert "/admin/static/marketing.css" in response.text
