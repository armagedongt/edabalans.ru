import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.intensive_web_access import issue_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AttributionEvent, User  # noqa: E402


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
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_auth_secret="test-secret",
        personal_masterclass_target_url="https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        telegram_channel_post_base_url="https://t.me/Fitness_Talks",
    )
    return TestClient(app), factory


def issue(factory: sessionmaker[Session], platform: str) -> str:
    with factory() as db:
        user = User(data_origin="native", first_seen_at=datetime.now(timezone.utc))
        db.add(user)
        db.flush()
        token, _ = issue_access_token(db, user.id, platform)
        db.commit()
        return token


def test_personal_masterclass_link_records_trusted_platform() -> None:
    client, factory = make_client()
    token = issue(factory, "max")

    response = client.get(
        f"/m/{token}?utm_source=message&from=telegram",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai"
    assert response.headers["cache-control"] == "no-store"
    with factory() as db:
        event = db.scalar(select(AttributionEvent))
        assert event is not None
        assert event.event_type == "personal_masterclass_link_open"
        assert event.source_raw == "max"
        assert event.utm_source == "message"
        assert event.landing_url == "masterclass_site"
    app.dependency_overrides.clear()


def test_personal_channel_post_link_is_telegram_only() -> None:
    client, factory = make_client()
    telegram_token = issue(factory, "telegram")
    max_token = issue(factory, "max")

    response = client.get(f"/p/260/{telegram_token}", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "https://t.me/Fitness_Talks/260"
    assert client.get(f"/p/260/{max_token}", follow_redirects=False).status_code == 404
    assert client.get("/p/260/not-a-token", follow_redirects=False).status_code == 404
    app.dependency_overrides.clear()
