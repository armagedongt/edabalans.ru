import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.main import app  # noqa: E402


def make_client() -> TestClient:
    return TestClient(app, base_url="https://app.edabalans.ru")


def login(client: TestClient) -> None:
    response = client.post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "test-admin-password"},
    )
    assert response.status_code == 200


def test_knowledge_base_requires_admin_session() -> None:
    client = make_client()
    page = client.get("/admin/knowledge-base")
    assert page.status_code == 200
    assert 'id="login-form"' in page.text
    assert client.get("/admin/api/knowledge-base").status_code == 401
    assert client.get("/admin/static/knowledge-base.js").status_code == 401


def test_knowledge_base_lists_and_renders_documents() -> None:
    client = make_client()
    login(client)

    page = client.get("/admin/knowledge-base")
    assert page.status_code == 200
    assert 'id="wiki-tree"' in page.text

    catalog = client.get("/admin/api/knowledge-base")
    assert catalog.status_code == 200
    sections = catalog.json()["sections"]
    assert [section["code"] for section in sections] == [
        "start",
        "knowledge",
        "working",
        "plans",
    ]
    assert [section["title"] for section in sections] == [
        "С чего начать",
        "База знаний",
        "Проект и эксплуатация",
        "Планы",
    ]
    paths = {
        document["path"]
        for section in sections
        for document in section["documents"]
    }
    assert "docs/knowledge-base/LEGAL_DOCUMENTS.md" in paths
    assert "docs/knowledge-base/modules/masterclass/README.md" in paths
    assert "docs/knowledge-base/modules/masterclass/COURSE_STRUCTURE_CONTRACT.md" in catalog.json()["all_paths"]
    masterclass = next(
        document
        for section in sections
        for document in section["documents"]
        if document["path"] == "docs/knowledge-base/modules/masterclass/README.md"
    )
    assert masterclass["parts"] == ["modules", "masterclass", "Обзор"]

    document = client.get(
        "/admin/api/knowledge-base/document",
        params={"path": "docs/knowledge-base/LEGAL_DOCUMENTS.md"},
    )
    assert document.status_code == 200
    assert document.json()["title"] == "Юридические документы и сбор данных"
    assert "<h1" in document.json()["html"]
    assert "Постоянные публичные адреса" in document.json()["html"]


def test_knowledge_base_searches_content_and_rejects_unknown_paths() -> None:
    client = make_client()
    login(client)

    search = client.get("/admin/api/knowledge-base", params={"q": "botfather"})
    assert search.status_code == 200
    found = {
        document["path"]
        for section in search.json()["sections"]
        for document in section["documents"]
    }
    assert "docs/knowledge-base/LEGAL_DOCUMENTS.md" in found
    assert "docs/knowledge-base/modules/masterclass/COURSE_STRUCTURE_CONTRACT.md" in search.json()["all_paths"]

    traversal = client.get(
        "/admin/api/knowledge-base/document",
        params={"path": "../../.env"},
    )
    assert traversal.status_code == 404
