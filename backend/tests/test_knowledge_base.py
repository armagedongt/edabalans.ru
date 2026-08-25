import json
import os
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app import knowledge_routes  # noqa: E402

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
    assert client.get("/admin/api/project-map").status_code == 401
    assert client.get("/admin/static/knowledge-base.js").status_code == 401


def test_knowledge_base_lists_and_renders_documents() -> None:
    client = make_client()
    login(client)

    page = client.get("/admin/knowledge-base")
    assert page.status_code == 200
    assert 'id="wiki-tree"' in page.text
    assert 'data-view="map"' in page.text
    assert 'data-view="documents"' in page.text

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


def project_map_payload(*, schema_version: int = 1) -> dict:
    return {
        "schema_version": schema_version,
        "modules": [
            {
                "id": "project-knowledge-viewer",
                "parent": None,
                "card": "docs/knowledge-base/OWNER_PROJECT_GUIDE.md",
                "title": "Карта проекта",
                "summary": "Навигация по модулям.",
                "document_status": "current",
                "implementation_status": "implemented",
                "capabilities": ["Показывает связи"],
                "boundary": "Не редактирует registry.",
                "truths": ["docs/modules.toml"],
                "runtime_services": ["backend"],
                "admin_urls": ["/admin/knowledge-base"],
                "public_urls": [],
                "sources": [],
                "relations": {
                    "reads_from": [],
                    "writes_to": [],
                    "depends_on": [],
                    "events_in": [],
                    "events_out": [],
                },
                "files": [],
                "routes": [],
                "tables": [],
                "symbols": [],
                "plans": [],
            }
        ],
        "relations": [],
        "files": [],
        "routes": [],
        "tables": [],
        "symbols": [],
        "derived_outputs": [],
        "plans": [],
        "cross_project_plans": [],
    }


def write_project_map(
    path: Path,
    *,
    schema_version: int = 1,
    payload: dict | None = None,
) -> None:
    path.write_text(
        json.dumps(
            payload or project_map_payload(schema_version=schema_version),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_project_map_returns_checked_in_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest = tmp_path / "module-inventory.json"
    write_project_map(manifest)
    monkeypatch.setattr(knowledge_routes, "PROJECT_MAP_PATH", manifest)
    client = make_client()
    login(client)

    response = client.get("/admin/api/project-map")

    assert response.status_code == 200
    assert response.json()["schema_version"] == 1
    assert response.json()["modules"][0]["id"] == "project-knowledge-viewer"


def test_project_map_serves_generated_repository_inventory() -> None:
    client = make_client()
    login(client)

    response = client.get("/admin/api/project-map")

    assert response.status_code == 200
    assert response.json()["schema_version"] == 1
    assert any(
        module["id"] == "admin.project-knowledge"
        for module in response.json()["modules"]
    )


def test_project_map_reports_missing_invalid_and_unknown_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest = tmp_path / "module-inventory.json"
    monkeypatch.setattr(knowledge_routes, "PROJECT_MAP_PATH", manifest)
    client = make_client()
    login(client)

    missing = client.get("/admin/api/project-map")
    assert missing.status_code == 503
    assert missing.json()["detail"] == "project map is temporarily unavailable"

    manifest.write_text("not json", encoding="utf-8")
    invalid = client.get("/admin/api/project-map")
    assert invalid.status_code == 503

    write_project_map(manifest, schema_version=2)
    unsupported = client.get("/admin/api/project-map")
    assert unsupported.status_code == 503
    assert unsupported.json()["detail"] == "project map schema is not supported"

    missing_array = project_map_payload()
    missing_array.pop("relations")
    write_project_map(manifest, payload=missing_array)
    assert client.get("/admin/api/project-map").status_code == 503

    duplicate_id = project_map_payload()
    duplicate_id["modules"].append(dict(duplicate_id["modules"][0]))
    write_project_map(manifest, payload=duplicate_id)
    assert client.get("/admin/api/project-map").status_code == 503

    invalid_relations = project_map_payload()
    invalid_relations["modules"][0]["relations"].pop("reads_from")
    write_project_map(manifest, payload=invalid_relations)
    assert client.get("/admin/api/project-map").status_code == 503


def test_control_portal_links_independent_tools_and_project_views() -> None:
    client = make_client()
    login(client)

    response = client.get("/control")

    assert response.status_code == 200
    assert 'href="/admin/knowledge-base?view=map"' in response.text
    assert 'href="/admin/knowledge-base?view=guide"' in response.text
    assert 'href="/admin/knowledge-base?view=plans"' in response.text
    assert 'href="/admin/knowledge-base?view=technical"' in response.text
    assert 'href="https://api.edabalans.ru/bot"' in response.text
    assert 'href="/bot"' not in response.text
