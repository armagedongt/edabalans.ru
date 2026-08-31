import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.auth import require_admin  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


def make_client() -> TestClient:
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
    app.dependency_overrides[require_admin] = lambda: "admin@example.test"
    return TestClient(app)


def test_public_markdown_document_is_seeded_and_rendered() -> None:
    client = make_client()
    response = client.get("/api/public-site/content/program")
    assert response.status_code == 200
    payload = response.json()
    assert payload["slug"] == "program"
    assert payload["version"] == 1
    assert payload["html"].strip()
    assert "public-site-version" not in payload["html"]
    assert "markdown" not in payload
    assert "updated_by" not in payload

    editor = client.get("/admin/api/public-site/content/program").json()["active"]
    assert editor["markdown"].startswith("<!-- public-site-version: 1 -->")
    assert editor["updated_by"]


def test_faq_is_returned_as_structured_items() -> None:
    client = make_client()
    response = client.get("/api/public-site/content/faq")
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "faq"
    assert payload["items"]
    assert all(item["question"].strip() and item["html"].strip() for item in payload["items"])


def test_admin_update_creates_version_and_rejects_stale_write() -> None:
    client = make_client()
    original = client.get("/admin/api/public-site/content/approach").json()["active"]
    update = client.put(
        "/admin/api/public-site/content/approach",
        json={"expected_version": original["version"], "markdown": "Новый текст\n\n- Один пункт"},
    )
    assert update.status_code == 200
    assert update.json()["active"]["version"] == 2
    assert update.json()["active"]["markdown"].startswith("<!-- public-site-version: 2 -->")
    assert "Новый текст" in client.get("/api/public-site/content/approach").json()["html"]

    stale = client.put(
        "/admin/api/public-site/content/approach",
        json={"expected_version": original["version"], "markdown": "Опоздавшая правка"},
    )
    assert stale.status_code == 409


def test_public_markdown_sanitizes_script_and_rejects_missing_document() -> None:
    client = make_client()
    original = client.get("/admin/api/public-site/content/recipes").json()["active"]
    response = client.put(
        "/admin/api/public-site/content/recipes",
        json={
            "expected_version": original["version"],
            "markdown": "Текст <script>alert(1)</script>\n\n![Фото](https://example.com/a.jpg)",
        },
    )
    assert response.status_code == 200
    rendered = response.json()["active"]["html"]
    assert "<script" not in rendered
    assert "https://example.com/a.jpg" in rendered
    assert client.get("/api/public-site/content/not-found").status_code == 404


def test_faq_rejects_missing_questions_and_empty_answers() -> None:
    client = make_client()
    original = client.get("/admin/api/public-site/content/faq").json()["active"]
    for markdown in ("Текст без вопроса", "## Вопрос без ответа"):
        response = client.put(
            "/admin/api/public-site/content/faq",
            json={"expected_version": original["version"], "markdown": markdown},
        )
        assert response.status_code == 422


def test_public_site_editor_requires_admin() -> None:
    client = make_client()
    app.dependency_overrides.pop(require_admin, None)
    try:
        assert client.get("/admin/api/public-site/content/program").status_code == 401
        assert client.put(
            "/admin/api/public-site/content/program",
            json={"expected_version": 1, "markdown": "Новая версия"},
        ).status_code == 401
    finally:
        app.dependency_overrides[require_admin] = lambda: "admin@example.test"
