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
    assert 'id="leaflet-map"' in page.text
    assert 'id="map-hour-range"' in page.text
    assert 'id="map-play"' in page.text
    assert 'id="map-previous"' in page.text
    assert 'id="map-next"' in page.text
    assert 'data-map-mode="precipitation"' in page.text
    assert 'data-map-mode="wind"' in page.text
    assert 'href="styles.css"' in page.text
    assert 'src="app.js"' in page.text
    assert client.get("/weather/styles.css").status_code == 200
    script = client.get("/weather/app.js")
    assert script.status_code == 200
    assert "mapForecastForSelectedDay" in script.text
    assert "tile.openstreetmap.org" in script.text
    assert "toggleMapPlayback" in script.text
    assert "wind_speed_unit: 'ms'" in script.text
