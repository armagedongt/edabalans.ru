import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.auth import require_admin  # noqa: E402
from app.main import app  # noqa: E402
from app.models import PublicHomepageEvent  # noqa: E402


def make_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), factory


def body(*, event: str = "page_open", section_id: str = "page_open") -> dict[str, str]:
    return {
        "event": event,
        "section_id": section_id,
        "viewer_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "page_id": "masterclass-homepage-2026",
        "page_path": "/preview/homepage-release-candidate",
    }


def test_collects_anonymous_open_and_section_once_per_session() -> None:
    client, factory = make_client()
    opening = body()
    section = {**opening, "event": "section_seen", "section_id": "pricing"}
    assert client.post("/api/public/homepage-analytics", json=opening).status_code == 200
    assert client.post("/api/public/homepage-analytics", json=section).status_code == 200
    assert client.post("/api/public/homepage-analytics", json=section).status_code == 200
    with factory() as db:
        rows = db.scalars(select(PublicHomepageEvent).order_by(PublicHomepageEvent.section_id)).all()
        assert [row.section_id for row in rows] == ["page_open", "pricing"]
        assert rows[0].viewer_key != opening["viewer_id"]
        assert len(rows[0].viewer_key) == 64
    app.dependency_overrides.clear()


def test_rejects_wrong_event_section_pair_and_unknown_section() -> None:
    client, _ = make_client()
    assert client.post("/api/public/homepage-analytics", json={**body(), "section_id": "pricing"}).status_code == 422
    assert client.post("/api/public/homepage-analytics", json={**body(event="section_seen", section_id="page_open")}).status_code == 422
    assert client.post("/api/public/homepage-analytics", json={**body(event="section_seen", section_id="unknown")}).status_code == 422
    app.dependency_overrides.clear()


def test_collects_one_semantic_interaction_and_active_reading_threshold() -> None:
    client, factory = make_client()
    opening = body()
    popup = {**opening, "event": "popup_open", "section_id": "program"}
    active = {**opening, "event": "page_active_30s", "section_id": "page_time"}

    assert client.post("/api/public/homepage-analytics", json=popup).status_code == 200
    assert client.post("/api/public/homepage-analytics", json=popup).status_code == 200
    assert client.post("/api/public/homepage-analytics", json=active).status_code == 200

    with factory() as db:
        rows = db.scalars(select(PublicHomepageEvent).order_by(PublicHomepageEvent.event_type)).all()
        assert [(row.event_type, row.section_id) for row in rows] == [
            ("page_active_30s", "page_time"),
            ("popup_open", "program"),
        ]
    app.dependency_overrides.clear()


def test_admin_summary_keeps_popup_tariff_and_reading_events_separate() -> None:
    client, _ = make_client()
    opening = body()
    for event, section_id in [
        ("page_open", "page_open"),
        ("section_seen", "pricing"),
        ("popup_open", "program"),
        ("checkout_open", "tariff_recipes"),
        ("checkout_started", "tariff_recipes"),
        ("section_active_10s", "pricing"),
        ("section_active_30s", "pricing"),
    ]:
        assert client.post(
            "/api/public/homepage-analytics",
            json={**opening, "event": event, "section_id": section_id},
        ).status_code == 200

    app.dependency_overrides[require_admin] = lambda: "test-admin"
    summary = client.get("/api/admin/public-homepage-analytics?days=30")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["sessions"] == 1
    assert next(item for item in payload["sections"] if item["id"] == "pricing")["sessions"] == 1
    assert {(item["event"], item["target"]) for item in payload["interactions"]} == {
        ("popup_open", "program"),
        ("checkout_open", "tariff_recipes"),
        ("checkout_started", "tariff_recipes"),
        ("section_active_10s", "pricing"),
        ("section_active_30s", "pricing"),
    }
    app.dependency_overrides.clear()


def test_release_candidate_contains_first_party_section_tracking() -> None:
    client, _ = make_client()

    response = client.get("/preview/homepage-release-candidate")

    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "Первый результат — уже через неделю" in response.text
    assert "/api/public/homepage-analytics" in response.text
    assert "page_active_180s" in response.text
    assert "section_active_30s" in response.text
    assert "tariff_recipes" in response.text
    assert "edb:homepage-analytics" in response.text
    assert "reviews_wall" in response.text
    assert client.get("/preview/homepage-mobile/favicon-no-outline.png").status_code == 200
    assert client.get("/public-site-assets/reviews/elena-review.mp3").status_code == 200
    app.dependency_overrides.clear()
