import os
from hashlib import sha256

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

from fastapi.testclient import TestClient

from app.config import get_settings

get_settings.cache_clear()

from app.main import app


def test_personal_game_is_public_and_not_indexable() -> None:
    response = TestClient(app).get("/game/")

    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert '<meta name="robots" content="noindex, nofollow, noarchive">' in response.text
    assert "Насколько хорошо мы" in response.text
    assert "sergey_sonechka_drawing_game_v2" in response.text


def test_personal_game_keeps_the_original_play_and_local_progress_flow() -> None:
    page = TestClient(app).get("/game/").text

    source = page.split("<body>\n", 1)[1].rsplit("\n</body>", 1)[0]
    assert sha256(source.encode("utf-8")).hexdigest() == (
        "c56a6c57041519e2b5e675844c9ded841e78ca302c3711ff8f83e4ae6b9fde6a"
    )
