import os
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import PublicVideoView  # noqa: E402
from app import public_video_analytics_routes as analytics_routes  # noqa: E402


def make_client() -> tuple[TestClient, sessionmaker[Session]]:
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
    return TestClient(app), factory


def payload(*, event: str = "video_engaged") -> dict:
    return {
        "event": event,
        "viewer_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "video_id": "homepage-vsl-2026-09-02",
        "page_path": "/preview/homepage-mobile",
        "last_position_sec": 0,
        "max_position_sec": 0,
        "watched_buckets_5s": [],
    }


def test_engagement_creates_one_anonymous_session() -> None:
    client, factory = make_client()
    body = payload()

    response = client.post("/api/public/video-analytics", json=body)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    with factory() as db:
        row = db.scalar(select(PublicVideoView))
        assert row is not None
        assert row.session_id == body["session_id"]
        assert row.viewer_key != body["viewer_id"]
        assert len(row.viewer_key) == 64
        assert row.event_count == 1
        assert row.status == "engaged"
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "video_id",
    [
        "homepage-vsl-2026-09-02",
        "homepage-anya-review-2026-09-01",
        "homepage-vsl-2026-02-13",
        "intensive-day-1-2026-09-03",
    ],
)
def test_supported_public_videos_are_accepted(video_id: str) -> None:
    client, factory = make_client()
    body = {**payload(), "video_id": video_id}

    response = client.post("/api/public/video-analytics", json=body)

    assert response.status_code == 200
    with factory() as db:
        row = db.scalar(select(PublicVideoView))
        assert row is not None
        assert row.video_id == video_id
    app.dependency_overrides.clear()


def test_progress_merges_buckets_and_positions_idempotently() -> None:
    client, factory = make_client()
    body = payload()
    assert client.post("/api/public/video-analytics", json=body).status_code == 200

    progress = {
        **body,
        "event": "video_progress",
        "last_position_sec": 20,
        "max_position_sec": 25,
        "watched_buckets_5s": [0, 5, 10, 15, 20],
    }
    assert client.post("/api/public/video-analytics", json=progress).status_code == 200
    assert client.post(
        "/api/public/video-analytics",
        json={**progress, "watched_buckets_5s": [15, 20, 25]},
    ).status_code == 200

    with factory() as db:
        row = db.scalar(select(PublicVideoView))
        assert row is not None
        assert row.max_position_sec == 25
        assert row.watched_buckets == [0, 5, 10, 15, 20, 25]
        assert row.event_count == 3
        assert row.status == "watching"
    app.dependency_overrides.clear()


def test_completion_is_sticky_after_exit() -> None:
    client, factory = make_client()
    body = payload()
    assert client.post("/api/public/video-analytics", json=body).status_code == 200
    completed = {
        **body,
        "event": "video_complete",
        "last_position_sec": 1_100,
        "max_position_sec": 1_100,
        "watched_buckets_5s": [0, 5, 10],
    }
    assert client.post("/api/public/video-analytics", json=completed).status_code == 200
    assert client.post(
        "/api/public/video-analytics", json={**completed, "event": "video_exit"}
    ).status_code == 200

    with factory() as db:
        row = db.scalar(select(PublicVideoView))
        assert row is not None
        assert row.completed is True
        assert row.completed_at is not None
        assert row.status == "completed"
    app.dependency_overrides.clear()


def test_session_rejects_another_viewer_and_invalid_payloads() -> None:
    client, _ = make_client()
    body = payload()
    assert client.post("/api/public/video-analytics", json=body).status_code == 200

    assert client.post(
        "/api/public/video-analytics",
        json={**body, "viewer_id": str(uuid.uuid4())},
    ).status_code == 409
    assert client.post(
        "/api/public/video-analytics",
        json={**payload(), "video_id": "unknown-video"},
    ).status_code == 422
    assert client.post(
        "/api/public/video-analytics",
        json={**payload(), "watched_buckets_5s": [3]},
    ).status_code == 422
    app.dependency_overrides.clear()


def test_progress_cannot_create_a_session_without_engagement() -> None:
    client, factory = make_client()
    body = payload(event="video_progress")

    response = client.post("/api/public/video-analytics", json=body)

    assert response.status_code == 409
    with factory() as db:
        assert db.scalar(select(PublicVideoView)) is None
    app.dependency_overrides.clear()


def test_new_sessions_are_rate_limited_per_network_client() -> None:
    client, _ = make_client()
    analytics_routes._rate_state.clear()

    for _ in range(analytics_routes.MAX_ENGAGEMENTS_PER_WINDOW):
        assert client.post(
            "/api/public/video-analytics", json=payload()
        ).status_code == 200

    assert client.post(
        "/api/public/video-analytics", json=payload()
    ).status_code == 429
    analytics_routes._rate_state.clear()
    app.dependency_overrides.clear()
