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


def test_tilda_origin_is_allowed_for_api_preflight() -> None:
    response = client.options(
        "/api/apps/metabolism",
        headers={
            "Origin": "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai"


def test_strength_new_user_can_start_and_manage_own_workouts() -> None:
    response = client.get("/apps/strength.html")

    assert response.status_code == 200
    assert "Создать первую тренировку" in response.text
    assert "if(!app.isAdmin){\n      return;\n    }\n\n    var catalog =\n      activeCatalog();" not in response.text
    assert "body.email =\n      app.email;" in response.text
