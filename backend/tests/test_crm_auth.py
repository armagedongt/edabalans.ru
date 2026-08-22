import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

def make_client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def test_crm_requires_authentication() -> None:
    response = make_client().get("/crm", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin?next=/crm"


def test_admin_api_requires_authentication() -> None:
    response = make_client().get("/admin/api/summary")
    assert response.status_code == 401


def test_unified_admin_requires_authentication() -> None:
    response = make_client().get("/admin")
    assert response.status_code == 200
    assert 'id="login-form"' in response.text


def test_unified_admin_assets_require_authentication() -> None:
    response = make_client().get("/admin/static/admin.js")
    assert response.status_code == 401


def test_cross_module_user_summary_requires_authentication() -> None:
    response = make_client().get("/admin/api/users/00000000-0000-0000-0000-000000000001/modules")
    assert response.status_code == 401


def test_login_creates_shared_admin_session() -> None:
    client = make_client()
    response = client.post(
        "/admin/api/login",
        json={"username": "ADMIN@example.com", "password": "test-admin-password"},
    )
    assert response.status_code == 200
    assert "edabalans_admin=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    page = client.get("/admin")
    assert page.status_code == 200
    assert 'id="admin-content"' in page.text


def test_login_rejects_wrong_password() -> None:
    response = make_client().post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "wrong"},
    )
    assert response.status_code == 401


def test_login_assets_are_public() -> None:
    response = make_client().get("/admin/static/admin-login.js")
    assert response.status_code == 200
