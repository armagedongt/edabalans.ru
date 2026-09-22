import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.auth import require_admin  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import PublicHomepageEvent  # noqa: E402
from app.public_homepage_analytics_routes import CTA_IDS, SECTION_IDS  # noqa: E402


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
    cta = {**opening, "event": "cta_click", "section_id": "pricing_hero"}
    assert client.post("/api/public/homepage-analytics", json=opening).status_code == 200
    assert client.post("/api/public/homepage-analytics", json=section).status_code == 200
    assert client.post("/api/public/homepage-analytics", json=section).status_code == 200
    assert client.post("/api/public/homepage-analytics", json=cta).status_code == 200
    assert client.post("/api/public/homepage-analytics", json=cta).status_code == 200
    with factory() as db:
        rows = db.scalars(select(PublicHomepageEvent).order_by(PublicHomepageEvent.event_type)).all()
        assert {(row.event_type, row.section_id) for row in rows} == {
            ("page_open", "page_open"),
            ("section_seen", "pricing"),
            ("cta_click", "pricing_hero"),
        }
        assert rows[0].viewer_key != opening["viewer_id"]
        assert len(rows[0].viewer_key) == 64
    app.dependency_overrides.clear()


def test_rejects_wrong_event_section_pair_and_unknown_section() -> None:
    client, _ = make_client()
    assert client.post("/api/public/homepage-analytics", json=body(event="section_seen", section_id="result_21_days")).status_code == 200
    assert client.post("/api/public/homepage-analytics", json={**body(), "section_id": "pricing"}).status_code == 422
    assert client.post("/api/public/homepage-analytics", json={**body(event="section_seen", section_id="page_open")}).status_code == 422
    assert client.post("/api/public/homepage-analytics", json={**body(event="section_seen", section_id="pricing_hero")}).status_code == 422
    assert client.post("/api/public/homepage-analytics", json={**body(event="cta_click", section_id="pricing")}).status_code == 422
    assert client.post("/api/public/homepage-analytics", json={**body(event="section_seen", section_id="unknown")}).status_code == 422
    app.dependency_overrides.clear()


def test_admin_summary_separates_reach_ctas_and_preview_paths() -> None:
    client, _ = make_client()
    app.dependency_overrides[require_admin] = lambda: "test-admin"
    session = body()
    preview_session = {**body(), "page_path": "/preview/homepage-version/next"}
    for payload in (
        session,
        {**session, "event": "section_seen", "section_id": "pricing"},
        {**session, "event": "cta_click", "section_id": "pricing_hero"},
        preview_session,
    ):
        assert client.post("/api/public/homepage-analytics", json=payload).status_code == 200

    response = client.get("/api/admin/public-homepage-analytics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["sessions"] == 2
    assert {item["path"]: item["sessions"] for item in payload["page_paths"]} == {
        "/preview/homepage-release-candidate": 1,
        "/preview/homepage-version/next": 1,
    }
    assert next(item for item in payload["sections"] if item["id"] == "pricing")["sessions"] == 1
    assert next(item for item in payload["ctas"] if item["id"] == "pricing_hero")["sessions"] == 1
    app.dependency_overrides.clear()


def test_release_candidate_contains_first_party_section_tracking() -> None:
    client, _ = make_client()

    response = client.get("/preview/homepage-release-candidate")

    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "Первый результат — уже через неделю" in response.text
    assert "/api/public/homepage-analytics" in response.text
    assert "reviews_wall" in response.text
    assert client.get("/preview/homepage-mobile/favicon-no-outline.png").status_code == 200
    assert client.get("/public-site-assets/reviews/elena-review.mp3").status_code == 200
    app.dependency_overrides.clear()


def test_next_homepage_tracks_declared_sections_and_each_pricing_cta_position() -> None:
    client, _ = make_client()

    response = client.get("/preview/homepage-version/next")

    assert response.status_code == 200
    assert "document.querySelectorAll('[data-analytics-section]')" in response.text
    assert "send('cta_click', cta.dataset.analyticsCta)" in response.text
    assert "homepage_section_seen" in response.text
    assert "homepage_cta_click" in response.text
    assert "window.ym(97331502" in response.text
    for section_id in SECTION_IDS:
        assert f'data-analytics-section="{section_id}"' in response.text
    for cta_id in CTA_IDS:
        assert f'data-analytics-cta="{cta_id}"' in response.text
    assert response.text.count('href="#masterclass-title">01. О Мастер-классе</a>') == 2
    assert response.text.count('href="#free-intensive-title">14. Есть сомнения?</a>') == 2
    app.dependency_overrides.clear()
