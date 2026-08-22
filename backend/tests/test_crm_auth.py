import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_crm_requires_authentication() -> None:
    response = client.get("/crm")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="Edabalans CRM"'


def test_admin_api_requires_authentication() -> None:
    response = client.get("/admin/api/summary")
    assert response.status_code == 401


def test_unified_admin_requires_authentication() -> None:
    response = client.get("/admin")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="Edabalans CRM"'


def test_unified_admin_assets_require_authentication() -> None:
    response = client.get("/admin/static/admin.js")
    assert response.status_code == 401


def test_cross_module_user_summary_requires_authentication() -> None:
    response = client.get("/admin/api/users/00000000-0000-0000-0000-000000000001/modules")
    assert response.status_code == 401
