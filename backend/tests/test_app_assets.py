import os
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


client = TestClient(app)


def test_stable_embed_loader_is_public() -> None:
    response = client.get("/embed.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "data-edabalans-app" in response.text


def test_application_fragments_use_server_api() -> None:
    for app_code in ("dqs", "strength", "metabolism"):
        response = client.get(f"/apps/{app_code}.html")
        assert response.status_code == 200
        assert "api.edabalans.ru/api/apps/" in response.text
        assert "REDACTED_LEGACY_APPS_SCRIPT_URL" not in response.text
        lowered = response.text.lower()
        assert "google" not in lowered
        assert "apps script" not in lowered


def test_production_admin_assets_do_not_name_legacy_storage() -> None:
    static_dir = Path(__file__).resolve().parents[1] / "app" / "static"
    for asset in ("admin.js", "crm.js"):
        lowered = (static_dir / asset).read_text(encoding="utf-8").lower()
        assert "google" not in lowered
        assert "apps script" not in lowered


def test_unknown_application_fragment_is_404() -> None:
    assert client.get("/apps/unknown.html").status_code == 404


def test_masterclass_fragments_and_shared_assets_are_public() -> None:
    account = client.get("/apps/account.html")
    assert account.status_code == 200
    assert 'id="account-app"' in account.text
    assert "/api/account" in account.text
    assert 'data-edabalans-app="' in account.text
    for app_code in ("onboarding-questionnaire", "masterclass-offers", "recipes-part-1", "recipes-part-2", "closing-review"):
        response = client.get(f"/apps/{app_code}.html")
        assert response.status_code == 200
        assert f'id="{app_code}-app"' in response.text
        assert "masterclass.js" in response.text
    assert client.get("/assets/masterclass.js").status_code == 200
    assert client.get("/assets/masterclass.css").status_code == 200
    assert client.get("/assets/max-logo.png").status_code == 200
    course = client.get("/apps/masterclass-course.html")
    assert course.status_code == 200
    assert 'id="masterclass-course-app"' in course.text
    assert "api/masterclass/course" in course.text
    assert "code==='dqs'||code==='closing-review'" in course.text
    loader = client.get("/embed.js").text
    assert "data-edabalans-placement" in loader
    assert "data-edabalans-placement-token" in loader
    assert "onboarding-questionnaire" in loader
    assert "tildaIdentityRequired" in loader
    assert "tma__getProfileObjFromLS" in loader
    assert "detectTildaMemberEmail" in loader
    assert "waitForTildaEmail" in loader
    assert "protectedApps ? detectTildaMemberEmail() : detectTildaEmail()" in loader
    assert "remembered.source === 'tilda'" not in loader
    assert "remember(detected, '', 0, 'tilda')" in loader
    assert "Откройте приложение из личного кабинета" in loader
    assert "masterclass-course" in loader
    assert "'account': true" in loader
    assert "hideTildaUserbar" in loader
    assert "data-edabalans-legal-footer" in loader
    assert "Воронцов Сергей" in loader
    assert "data-edabalans-account-url" in loader
    assert "source: identitySource" in loader
    assert "identity.source==='tilda'" in course.text
    assert "function authHeaders()" in course.text
    assert "Похудение — это есть!" in course.text
    assert ".tlk-userbar{display:none!important}" in course.text
    assert "Темы видны заранее" not in course.text
    assert client.get("/legal/disclaimer.html").status_code == 200
    assert client.get("/legal/privacy.html").status_code == 200
    masterclass = client.get("/assets/masterclass.js").text
    assert "Authorization='Bearer '" in masterclass
    assert "placement_token" in masterclass


def test_masterclass_sales_fragment_uses_server_price_codes() -> None:
    response = client.get("/apps/masterclass-sales.html")
    assert response.status_code == 200
    assert 'id="masterclass-sales-app"' in response.text
    assert "/api/pricing/site" in response.text
    assert "/api/pricing/site/checkout" in response.text
    assert "site.masterclass.basic" in response.text
    assert "site.masterclass.recipes" in response.text
    assert "site.masterclass.consult" in response.text
    assert "location.hash=result.cart_command" in response.text
    loader = client.get("/embed.js").text
    assert "'masterclass-sales': 'masterclass-sales-app'" in loader


def test_dqs_notifies_course_only_after_server_save() -> None:
    response = client.get("/apps/dqs.html")

    assert response.status_code == 200
    assert "'edabalans:app-completed'" in response.text
    assert "app:'dqs'" in response.text


def test_tilda_origin_is_allowed_for_api_preflight() -> None:
    response = client.options(
        "/api/apps/metabolism",
        headers={
            "Origin": "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_strength_new_user_can_start_and_manage_own_workouts() -> None:
    response = client.get("/apps/strength.html")

    assert response.status_code == 200
    assert "Создать первую тренировку" in response.text
    assert "if(!app.isAdmin){\n      return;\n    }\n\n    var catalog =\n      activeCatalog();" not in response.text
    assert "body.email =\n      app.email;" in response.text
