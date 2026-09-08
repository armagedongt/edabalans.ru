import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

from fastapi.testclient import TestClient

from app.config import get_settings

get_settings.cache_clear()

from app.main import app


def test_weather_page_requires_admin_access() -> None:
    response = TestClient(app).get("/weather")
    assert response.status_code == 401


def test_weather_page_and_assets_are_available_to_admin() -> None:
    client = TestClient(app)
    auth = ("admin@example.com", "test-admin-password")
    page = client.get("/weather", auth=auth)
    assert page.status_code == 200
    assert 'id="weather-app"' in page.text
    assert client.get("/weather/app.js", auth=auth).status_code == 200
