import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


get_settings.cache_clear()


def make_client() -> TestClient:
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
    return TestClient(app, base_url="https://testserver")


def login(client: TestClient) -> None:
    response = client.post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "test-admin-password"},
    )
    assert response.status_code == 200


def test_shared_page_requires_admin_to_save_and_is_public_after_save() -> None:
    client = make_client()
    empty = client.get("/api/intensive/day-1")
    assert empty.status_code == 200
    assert empty.json()["html"] is None
    assert empty.json()["version"] == 0

    denied = client.put(
        "/admin/api/intensive/day-1",
        json={"html": "<h1>Новый текст</h1>", "version": 0},
    )
    assert denied.status_code == 401

    login(client)
    saved = client.put(
        "/admin/api/intensive/day-1",
        json={
            "html": '<h1 onclick="bad()">Новый текст</h1><script>alert(1)</script><p><a href="javascript:bad()">Ссылка</a></p>',
            "version": 0,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["version"] == 1
    assert saved.json()["html"] == "<h1>Новый текст</h1><p><a>Ссылка</a></p>"

    public = client.get("/api/intensive/day-1")
    assert public.status_code == 200
    assert public.json()["html"] == saved.json()["html"]
    assert public.json()["version"] == 1


def test_shared_page_rejects_stale_save_and_unknown_day() -> None:
    client = make_client()
    login(client)
    first = client.put(
        "/admin/api/intensive/day-2",
        json={"html": "<h1>Первая версия</h1>", "version": 0},
    )
    assert first.status_code == 200

    stale = client.put(
        "/admin/api/intensive/day-2",
        json={"html": "<h1>Устаревшая версия</h1>", "version": 0},
    )
    assert stale.status_code == 409
    assert client.get("/api/intensive/day-5").status_code == 404
