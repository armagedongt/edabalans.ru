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


def test_crm_requires_authentication() -> None:
    response = make_client().get("/crm", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin?next=/crm"


def test_legacy_control_and_people_redirect_to_single_admin_surfaces() -> None:
    client = make_client()
    login = client.post("/admin/api/login", json={"username": "admin@example.com", "password": "test-admin-password"})
    assert login.status_code == 200
    assert client.get("/control", follow_redirects=False).headers["location"] == "/admin"
    people = client.get("/admin/users?user=client-id&q=ivan", follow_redirects=False)
    assert people.status_code == 303
    assert people.headers["location"] == "/crm?user=client-id&q=ivan"


def test_admin_api_requires_authentication() -> None:
    response = make_client().get("/admin/api/summary")
    assert response.status_code == 401


def test_masterclass_offer_client_context_api_requires_authentication() -> None:
    client = make_client()
    assert client.get("/api/masterclass/admin/offer-preview/clients?q=test").status_code == 401
    assert client.get(
        "/api/masterclass/admin/offer-preview/clients/00000000-0000-0000-0000-000000000000"
    ).status_code == 401


def test_course_structure_api_requires_authentication() -> None:
    client = make_client()
    assert client.get("/admin/api/courses").status_code == 401
    assert client.get("/admin/api/courses/masterclass-21/structure").status_code == 401
    assert client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": 1, "manifest": {}},
    ).status_code == 401
    assert client.post(
        "/admin/api/courses/masterclass-21/structure/versions/1/restore",
        json={"expected_version": 1},
    ).status_code == 401


def test_unified_admin_requires_authentication() -> None:
    response = make_client().get("/admin")
    assert response.status_code == 200
    assert 'id="login-form"' in response.text


def test_content_catalog_uses_unified_admin_shell() -> None:
    response = make_client().get("/admin/content")
    assert response.status_code == 200
    assert 'id="login-form"' in response.text


def test_retired_masterclass_admin_surfaces_are_not_available() -> None:
    client = make_client()
    assert client.get("/admin/masterclass").status_code == 404
    assert client.get("/admin/masterclass-preview").status_code == 404


def test_masterclass_course_preview_requires_authentication() -> None:
    response = make_client().get("/admin/masterclass-course-preview")
    assert response.status_code == 200
    assert 'id="login-form"' in response.text


def test_masterclass_course_preview_is_available_after_login() -> None:
    client = make_client()
    login = client.post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "test-admin-password"},
    )
    assert login.status_code == 200
    response = client.get("/admin/masterclass-course-preview")
    assert response.status_code == 200
    assert "Структура Мастер-класса" in response.text


def test_masterclass_designs_are_available_after_login() -> None:
    client = make_client()
    login = client.post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "test-admin-password"},
    )
    assert login.status_code == 200
    response = client.get("/admin/masterclass-designs")
    assert response.status_code == 200
    assert "Структура Мастер-класса" in response.text


def test_masterclass_offers_preview_requires_authentication() -> None:
    response = make_client().get(
        "/admin/masterclass-offers-preview", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == (
        "/admin?next=/admin/masterclass-offers-preview"
    )


def test_masterclass_offers_preview_uses_canonical_course_sources() -> None:
    client = make_client()
    login = client.post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "test-admin-password"},
    )
    assert login.status_code == 200
    response = client.get("/admin/masterclass-offers-preview")
    assert response.status_code == 200
    assert "Сценарный предпросмотр" in response.text
    assert "/api/masterclass/admin/offer-stages" in response.text
    assert "/api/masterclass/admin/offer-preview" in response.text
    assert "Система рецептов" in response.text
    assert "EdabalansMasterclassOfferView.markup(data)" in response.text
    assert response.headers["cache-control"] == "no-store"
    client_mode = client.get("/admin/masterclass-offers-preview?mode=client")
    assert client_mode.status_code == 200
    assert 'href="/admin/masterclass-offers-preview?mode=client" aria-selected="true"' in client_mode.text
    assert 'id="scenario-mode" hidden' in client_mode.text
    assert 'id="client-mode" class="client-mode is-active"' in client_mode.text
    assert 'id="client-search-submit">Найти</button>' in client_mode.text
    assert "Клиент с таким email не найден." in client_mode.text
    assert "submit.onclick=search" in client_mode.text
    assert "function showClient(id)" in client_mode.text
    assert "clientInput.oninput=null" in client_mode.text
    assert "То, что увидит клиент" not in client_mode.text
    assert "Можно добавить к мастер-классу" in client_mode.text
    assert "EdabalansMasterclassOfferView.headerMarkup()" in client_mode.text


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
    assert "Domain=.edabalans.ru" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
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
