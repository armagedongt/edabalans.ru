import os
import time
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.intensive_web_access import (  # noqa: E402
    ACCESS_TOKEN_TTL,
    DAY_DELAY,
    OFFER_DISCOUNT,
    SESSION_COOKIE,
    _signed_value,
    access_token_row,
    create_offer_token,
    day_unlocked,
    issue_access_token,
    mark_assignment_opened,
    offer_for_user,
    offer_user_id,
    open_day,
    progress_rows,
    state_payload,
)
from app.main import app  # noqa: E402
from app.models import AttributionEvent, CourseEvent, CourseStageProgress, User  # noqa: E402


SECRET = "intensive-test-secret"


def make_client(**settings_overrides: str) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_auth_secret=SECRET,
        **settings_overrides,
    )
    return TestClient(app), factory


def create_user(factory: sessionmaker[Session]) -> User:
    with factory() as db:
        user = User(data_origin="native", first_seen_at=datetime.now(timezone.utc))
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def test_personal_link_restores_server_identity_and_ignores_forged_source() -> None:
    client, factory = make_client()
    user = create_user(factory)
    with factory() as db:
        token, _ = issue_access_token(db, user.id, "telegram")
        db.commit()

    entry = client.get(
        f"/intensive/start?i={token}&from=max&utm_source=yandex&yclid=click-1",
        follow_redirects=False,
    )
    assert entry.status_code == 307
    assert entry.headers["location"].startswith("/intensive/day-1")
    assert "edabalans_intensive_session" in entry.headers["set-cookie"]

    page = client.get(entry.headers["location"])
    assert page.status_code == 200
    state = client.get("/api/intensive/state").json()
    assert state["identified"] is True
    assert state["platform"] == "telegram"
    assert state["opened_days"] == [1]
    assert state["unlocked_days"] == [1]
    assert state["current_day"] == 1

    for day in range(2, 5):
        locked = client.get(f"/intensive/day-{day}", follow_redirects=False)
        assert locked.status_code == 307
        assert locked.headers["location"] == "/intensive"

    with factory() as db:
        event = db.scalar(select(AttributionEvent))
        assert event is not None
        assert event.source_raw == "telegram"
        assert event.utm_source == "yandex"
        assert event.ref_code == "click-1"
        assert "i=" not in (event.landing_url or "")

    second_device = TestClient(app)
    replay = second_device.get(f"/intensive/start?i={token}", follow_redirects=False)
    assert replay.status_code == 307
    assert replay.headers["location"].startswith("/intensive/day-1")
    assert second_device.get("/api/intensive/state").json()["platform"] == "telegram"
    with factory() as db:
        row = access_token_row(db, token)
        assert row is not None
        assert row.consumed_at is None
    app.dependency_overrides.clear()


def test_progress_is_durable_in_course_tables_and_day_four_starts_offer() -> None:
    _, factory = make_client()
    user = create_user(factory)
    started = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    with factory() as db:
        assert open_day(db, user.id, 1, now=started) is not None
        assert mark_assignment_opened(db, user.id, 1, "telegram", now=started) is not None
        rows = progress_rows(db, user.id)
        assert DAY_DELAY == timedelta(hours=23)
        assert day_unlocked(rows, 2, now=started + timedelta(hours=23) - timedelta(seconds=1)) is False
        assert open_day(db, user.id, 2, now=started + timedelta(hours=23)) is not None
        assert mark_assignment_opened(db, user.id, 2, "max", now=started + timedelta(hours=23)) is not None
        assert open_day(db, user.id, 3, now=started + timedelta(hours=46)) is not None
        assert mark_assignment_opened(db, user.id, 3, "telegram", now=started + timedelta(hours=46)) is not None
        assert open_day(db, user.id, 4, now=started + timedelta(hours=69)) is not None
        offer = offer_for_user(db, user.id)
        assert offer is not None
        assert offer.snapshot["discount_amount"] == OFFER_DISCOUNT
        payload = state_payload(db, user.id, "telegram", now=started + timedelta(hours=69))
        assert payload["opened_days"] == [1, 2, 3, 4]
        assert payload["assignment_days"] == [1, 2, 3]
        assert payload["offer"]["active"] is True
        assert db.scalar(select(func.count(CourseEvent.id))) == 8
        db.commit()
    app.dependency_overrides.clear()


def test_public_entry_has_all_four_days_without_creating_progress() -> None:
    client, factory = make_client()

    entry = client.get("/intensive/start", follow_redirects=False)
    assert entry.status_code == 307
    assert entry.headers["location"] == "/intensive"
    assert "edabalans_intensive_session" not in entry.headers

    state = client.get("/api/intensive/state").json()
    assert state["identified"] is False
    assert state["unlocked_days"] == [1, 2, 3, 4]
    assert state["current_day"] == 1

    for day in range(1, 5):
        assert client.get(f"/intensive/day-{day}").status_code == 200

    state_after_browsing = client.get("/api/intensive/state").json()
    assert state_after_browsing["identified"] is False
    assert state_after_browsing["unlocked_days"] == [1, 2, 3, 4]
    with factory() as db:
        assert db.scalar(select(func.count(CourseEvent.id))) == 0
        assert db.scalar(select(func.count(CourseStageProgress.id))) == 0
    app.dependency_overrides.clear()


def test_stale_personal_cookie_falls_back_to_public_access() -> None:
    client, factory = make_client()
    client.cookies.set(
        SESSION_COOKIE,
        _signed_value(
            SECRET,
            {
                "user_id": str(uuid.uuid4()),
                "platform": "telegram",
                "exp": int(time.time()) + 60,
            },
        ),
    )

    state = client.get("/api/intensive/state").json()
    assert state["identified"] is False
    assert state["unlocked_days"] == [1, 2, 3, 4]
    for day in range(1, 5):
        assert client.get(f"/intensive/day-{day}").status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count(CourseStageProgress.id))) == 0
    app.dependency_overrides.clear()


def test_offer_token_is_opaque_and_bound_to_active_database_offer() -> None:
    _, factory = make_client()
    user = create_user(factory)
    started = datetime.now(timezone.utc)
    with factory() as db:
        open_day(db, user.id, 1, now=started - DAY_DELAY * 3)
        mark_assignment_opened(db, user.id, 1, "telegram", now=started - DAY_DELAY * 3)
        open_day(db, user.id, 2, now=started - DAY_DELAY * 2)
        mark_assignment_opened(db, user.id, 2, "telegram", now=started - DAY_DELAY * 2)
        open_day(db, user.id, 3, now=started - DAY_DELAY)
        mark_assignment_opened(db, user.id, 3, "telegram", now=started - DAY_DELAY)
        open_day(db, user.id, 4, now=started)
        offer = offer_for_user(db, user.id)
        assert offer is not None and offer.expires_at is not None
        token = create_offer_token(db, user.id, offer.expires_at)
        assert str(user.id) not in token
        assert offer_user_id(db, token) == user.id
        assert offer_user_id(db, token + "x") is None
        offer.status = "expired"
        db.flush()
        assert offer_user_id(db, token) is None
    app.dependency_overrides.clear()


def test_completed_participant_entry_opens_menu_and_offer_route_persists_token() -> None:
    client, factory = make_client()
    user = create_user(factory)
    started = datetime.now(timezone.utc) - timedelta(hours=70)
    with factory() as db:
        for day in range(1, 4):
            opened_at = started + timedelta(hours=23 * (day - 1))
            assert open_day(db, user.id, day, now=opened_at) is not None
            assert mark_assignment_opened(db, user.id, day, "telegram", now=opened_at) is not None
        assert open_day(db, user.id, 4, now=started + timedelta(hours=69)) is not None
        token, _ = issue_access_token(db, user.id, "telegram")
        db.commit()

    entry = client.get(f"/intensive/start?i={token}", follow_redirects=False)
    assert entry.status_code == 307
    assert entry.headers["location"] == "/intensive"

    response = client.get("/api/intensive/offer-token")
    assert response.status_code == 200
    offer_token = response.json()["token"]
    assert str(user.id) not in offer_token
    with factory() as db:
        assert offer_user_id(db, offer_token) == user.id
    app.dependency_overrides.clear()


def test_reopening_day_four_does_not_restart_offer_window() -> None:
    _, factory = make_client()
    user = create_user(factory)
    started = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    with factory() as db:
        for day in range(1, 4):
            opened_at = started + timedelta(hours=23 * (day - 1))
            open_day(db, user.id, day, now=opened_at)
            mark_assignment_opened(db, user.id, day, "telegram", now=opened_at)
        open_day(db, user.id, 4, now=started + timedelta(hours=69))
        first_offer = offer_for_user(db, user.id)
        assert first_offer is not None
        first_started_at = first_offer.started_at
        first_expires_at = first_offer.expires_at
        open_day(db, user.id, 4, now=started + timedelta(hours=70))
        second_offer = offer_for_user(db, user.id)
        assert second_offer is not None
        assert second_offer.started_at == first_started_at
        assert second_offer.expires_at == first_expires_at
    app.dependency_overrides.clear()


def test_expired_personal_token_is_rejected() -> None:
    _, factory = make_client()
    user = create_user(factory)
    issued = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with factory() as db:
        token, _ = issue_access_token(db, user.id, "max", now=issued)
        db.commit()
        assert access_token_row(db, token, now=issued + ACCESS_TOKEN_TTL + timedelta(seconds=1)) is None
    app.dependency_overrides.clear()


def test_elapsed_time_does_not_unlock_next_day_without_assignment_open() -> None:
    _, factory = make_client()
    user = create_user(factory)
    started = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    with factory() as db:
        assert open_day(db, user.id, 1, now=started) is not None
        rows = progress_rows(db, user.id)
        assert day_unlocked(rows, 2, now=started + timedelta(days=2)) is False
        assert open_day(db, user.id, 2, now=started + timedelta(days=2)) is None
    app.dependency_overrides.clear()


def test_configured_assignment_uses_trusted_platform_and_marks_progress() -> None:
    client, factory = make_client(
        intensive_day_1_telegram_post_url="https://t.me/Fitness_Talks/1001",
        intensive_day_1_max_post_url="https://max.ru/Fitness_Talks/1001",
    )
    user = create_user(factory)
    with factory() as db:
        token, _ = issue_access_token(db, user.id, "telegram")
        db.commit()

    client.get(f"/intensive/start?i={token}", follow_redirects=False)
    assert client.get("/intensive/day-1").status_code == 200
    forged = client.post("/api/intensive/day-1/post/max")
    assert forged.status_code == 403

    response = client.post("/api/intensive/day-1/post/telegram")
    assert response.status_code == 200
    assert response.json()["target_url"] == "https://t.me/Fitness_Talks/1001"
    state = client.get("/api/intensive/state").json()
    assert state["assignment_days"] == [1]
    with factory() as db:
        event = db.scalar(
            select(CourseEvent).where(
                CourseEvent.event_type == "intensive_required_post_open"
            )
        )
        assert event is not None
        assert event.details == {"day": 1, "messenger": "telegram"}
    app.dependency_overrides.clear()


def test_invalid_assignment_url_stays_closed() -> None:
    client, factory = make_client(
        intensive_day_1_telegram_post_url="javascript:alert(1)",
    )
    user = create_user(factory)
    with factory() as db:
        token, _ = issue_access_token(db, user.id, "telegram")
        db.commit()
    client.get(f"/intensive/start?i={token}", follow_redirects=False)
    client.get("/intensive/day-1")

    response = client.post("/api/intensive/day-1/post/telegram")
    assert response.status_code == 503
    assert client.get("/api/intensive/state").json()["assignment_days"] == []
    app.dependency_overrides.clear()


def test_personal_client_events_are_validated_and_idempotent() -> None:
    client, factory = make_client()
    assert client.post(
        "/api/intensive/events",
        json={"event_id": "anonymous", "event_type": "intensive_menu_open"},
    ).status_code == 401
    user = create_user(factory)
    with factory() as db:
        token, _ = issue_access_token(db, user.id, "telegram")
        db.commit()
    client.get(f"/intensive/start?i={token}", follow_redirects=False)
    client.get("/intensive/day-1")

    payload = {
        "event_id": "browser-event-1",
        "event_type": "video_progress",
        "day": 1,
        "video_id": "intensive-day-1",
        "progress_percent": 25,
        "platform": "max",
        "target_url": "https://untrusted.example/ignored",
    }
    first = client.post("/api/intensive/events", json=payload)
    second = client.post("/api/intensive/events", json={**payload, "event_id": "browser-event-2"})
    assert first.status_code == second.status_code == 200
    assert first.json()["event_id"] == second.json()["event_id"]

    forged = client.post(
        "/api/intensive/events",
        json={
            "event_id": "browser-event-3",
            "event_type": "intensive_max_click",
            "day": 1,
        },
    )
    assert forged.status_code == 422
    invalid_progress = client.post(
        "/api/intensive/events",
        json={
            "event_id": "browser-event-4",
            "event_type": "video_progress",
            "day": 1,
            "video_id": "intensive-day-1",
            "progress_percent": "Infinity",
        },
    )
    assert invalid_progress.status_code == 422
    with factory() as db:
        event = db.scalar(
            select(CourseEvent).where(CourseEvent.event_type == "video_progress")
        )
        assert event is not None
        assert event.details["platform"] == "telegram"
        assert "target_url" not in event.details
        assert db.scalar(
            select(func.count(CourseEvent.id)).where(
                CourseEvent.event_type == "video_progress"
            )
        ) == 1
    app.dependency_overrides.clear()


def test_accelerated_http_journey_reaches_day_four_and_offer() -> None:
    client, factory = make_client(
        intensive_day_1_telegram_post_url="https://t.me/Fitness_Talks/1001",
        intensive_day_2_telegram_post_url="https://t.me/Fitness_Talks/1002",
        intensive_day_3_telegram_post_url="https://t.me/Fitness_Talks/1003",
    )
    user = create_user(factory)
    with factory() as db:
        token, _ = issue_access_token(db, user.id, "telegram")
        db.commit()
    entry = client.get(f"/intensive/start?i={token}", follow_redirects=False)
    assert entry.headers["location"] == "/intensive/day-1"

    for day in range(1, 4):
        assert client.get(f"/intensive/day-{day}").status_code == 200
        assignment = client.post(f"/api/intensive/day-{day}/post/telegram")
        assert assignment.status_code == 200
        with factory() as db:
            progress = db.scalar(
                select(CourseStageProgress).where(
                    CourseStageProgress.user_id == user.id,
                    CourseStageProgress.course_code == "intensive",
                    CourseStageProgress.stage_number == day,
                )
            )
            assert progress is not None
            progress.first_opened_at = datetime.now(timezone.utc) - DAY_DELAY
            db.commit()
        assert client.get(f"/intensive/day-{day + 1}").status_code == 200

    state = client.get("/api/intensive/state").json()
    assert state["opened_days"] == [1, 2, 3, 4]
    assert state["assignment_days"] == [1, 2, 3]
    assert state["offer"]["active"] is True
    assert client.get("/api/intensive/offer-token").status_code == 200
    app.dependency_overrides.clear()
