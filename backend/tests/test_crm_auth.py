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


def test_payments_api_passes_pagination_offset(monkeypatch) -> None:
    import app.crm_routes as crm_routes

    captured = {}

    def fake_list_payments(_db, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(crm_routes, "list_payments", fake_list_payments)
    client = make_client()
    assert client.post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "test-admin-password"},
    ).status_code == 200

    response = client.get("/admin/api/payments?limit=100&offset=200")

    assert response.status_code == 200
    assert captured["limit"] == 100
    assert captured["offset"] == 200


def test_payments_query_applies_offset_and_stable_order() -> None:
    from datetime import datetime, timezone

    from app.crm_service import list_payments

    captured = {}

    class Result:
        @staticmethod
        def all():
            return []

    class Database:
        @staticmethod
        def execute(statement):
            captured["statement"] = statement
            return Result()

    snapshot = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
    assert list_payments(Database(), limit=100, offset=200, snapshot_at=snapshot) == []
    statement = captured["statement"]
    assert statement._offset_clause.value == 200
    assert statement._limit_clause.value == 100
    assert "payments.id DESC" in " ".join(map(str, statement._order_by_clauses))
    assert "payments.created_at <=" in str(statement)


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


def test_admin_surfaces_use_the_lightning_favicon() -> None:
    client = make_client()
    favicon_link = '<link rel="icon" type="image/svg+xml" href="/admin/static/admin-favicon.svg">'

    login_page = client.get("/admin")
    assert favicon_link in login_page.text

    favicon = client.get("/admin/static/admin-favicon.svg")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/svg+xml")
    assert "⚡" in favicon.text

    assert client.post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "test-admin-password"},
    ).status_code == 200
    for path in (
        "/admin",
        "/crm",
        "/admin/knowledge-base",
        "/admin/library",
        "/admin/courses",
        "/admin/courses/masterclass-21/structure",
        "/admin/products",
        "/admin/content",
        "/admin/marketing",
        "/admin/masterclass-offers-preview",
        "/admin/dqs",
        "/admin/strength",
        "/admin/metabolism",
        "/admin/messaging",
        "/admin/pricing",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert favicon_link in response.text, path


def test_content_catalog_uses_unified_admin_shell() -> None:
    response = make_client().get("/admin/content")
    assert response.status_code == 200
    assert 'id="login-form"' in response.text


def test_retired_masterclass_admin_surfaces_are_not_available() -> None:
    client = make_client()
    retired_paths = (
        "/admin/masterclass",
        "/admin/masterclass-preview",
        "/admin/masterclass-course-preview",
        "/admin/masterclass-designs",
    )
    for path in retired_paths:
        assert client.get(path).status_code == 404

    assert client.post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "test-admin-password"},
    ).status_code == 200
    for path in retired_paths:
        assert client.get(path).status_code == 404


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
    for page in (response, client_mode):
        assert "/admin/static/admin-shell.css" in page.text
        assert "/admin/static/admin-shell.js" in page.text


def test_unified_admin_assets_require_authentication() -> None:
    for asset in ("admin.js", "admin-shell.js", "admin-shell.css"):
        response = make_client().get(f"/admin/static/{asset}")
        assert response.status_code == 401


def test_unified_shell_is_loaded_by_main_admin_surfaces() -> None:
    client = make_client()
    login = client.post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "test-admin-password"},
    )
    assert login.status_code == 200
    for path in ("/admin", "/crm", "/admin/content", "/admin/library", "/admin/knowledge-base", "/admin/courses", "/admin/products"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "/admin/static/admin-shell.css" in response.text, path
        assert "/admin/static/admin-shell.js" in response.text, path


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
    page = client.get("/admin", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "/crm"
    page = client.get("/admin")
    assert page.status_code == 200
    assert 'id="crm-app"' in page.text


def test_login_rejects_wrong_password() -> None:
    response = make_client().post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "wrong"},
    )
    assert response.status_code == 401


def test_login_assets_are_public() -> None:
    response = make_client().get("/admin/static/admin-login.js")
    assert response.status_code == 200


def test_admin_session_last_30_days_and_password_rotation_revokes_it(monkeypatch) -> None:
    import app.auth as auth

    client = make_client()
    start = 2_000_000_000
    monkeypatch.setattr(auth.time, "time", lambda: start)
    login = client.post("/admin/api/login", json={
        "username": "admin@example.com", "password": "test-admin-password",
    })
    assert login.status_code == 200
    assert any("Max-Age=2592000" in value for value in login.headers.get_list("set-cookie"))
    token = client.cookies.get("edabalans_admin")
    monkeypatch.setattr(auth.time, "time", lambda: start + 29 * 86400)
    assert 'id="crm-app"' in client.get("/admin").text
    monkeypatch.setattr(auth.time, "time", lambda: start + 31 * 86400)
    assert 'id="login-form"' in client.get(
        "/admin", headers={"Cookie": f"edabalans_admin={token}"},
    ).text
    monkeypatch.setattr(auth.time, "time", lambda: start)
    client.cookies.set("edabalans_admin", token, domain=".edabalans.ru", path="/")
    assert 'id="crm-app"' in client.get("/admin").text
    monkeypatch.setattr(get_settings(), "admin_password", "rotated-test-password")
    assert 'id="login-form"' in client.get("/admin").text
    assert client.post("/admin/api/login", json={
        "username": "admin@example.com", "password": "test-admin-password",
    }).status_code == 401


def test_admin_cookie_cross_subdomain_and_logout() -> None:
    client = TestClient(app, base_url="https://edabalans.ru")
    client.cookies.set("edabalans_admin", "legacy-host-cookie", domain="edabalans.ru", path="/")
    assert client.post("/admin/api/login", json={
        "username": "admin@example.com", "password": "test-admin-password",
    }).status_code == 200
    assert len([c for c in client.cookies.jar if c.name == "edabalans_admin"]) == 1
    assert 'id="crm-app"' in client.get("https://app.edabalans.ru/admin").text
    assert 'id="login-form"' in client.get("https://unrelated.example/admin").text
    client.cookies.set("edabalans_admin", "legacy-host-cookie", domain="edabalans.ru", path="/")
    assert client.post("/admin/api/logout").status_code == 200
    assert not any(c.name == "edabalans_admin" for c in client.cookies.jar)
    assert 'id="login-form"' in client.get("https://app.edabalans.ru/admin").text


def test_independent_host_login_does_not_expand_cookie_trust() -> None:
    client = TestClient(app, base_url="https://independent.example")
    response = client.post("/admin/api/login", json={
        "username": "admin@example.com", "password": "test-admin-password",
    })
    assert response.status_code == 200
    assert "Domain=" not in response.headers["set-cookie"]
    assert 'id="crm-app"' in client.get("/admin").text
    assert client.post("/admin/api/logout").status_code == 200
    assert 'id="login-form"' in client.get("/admin").text
