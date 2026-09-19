import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

from fastapi.testclient import TestClient

from app.config import get_settings

get_settings.cache_clear()

from app.main import app


def test_weather_page_and_assets_are_public() -> None:
    client = TestClient(app)
    redirect = client.get("/weather", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/weather/"
    page = client.get("/weather/")
    assert page.status_code == 200
    assert 'id="weather-app"' in page.text
    assert 'id="windy-embed"' in page.text
    assert 'href="styles.css"' in page.text
    assert 'src="app.js"' in page.text
    assert client.get("/weather/styles.css").status_code == 200
    script = client.get("/weather/app.js")
    assert script.status_code == 200
    assert "windyMapUrl" in script.text
    assert "embed.windy.com/embed2.html" in script.text
    assert "renderWindyMap" in script.text
    assert "wind_direction_10m" in script.text
    assert "wind_speed_unit: 'ms'" in script.text
