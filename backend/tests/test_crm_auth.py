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
