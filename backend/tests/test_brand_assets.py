import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


client = TestClient(app)


def test_brand_icons_are_available_from_root_paths() -> None:
    expected = {
        "/favicon.ico": ("image/vnd.microsoft.icon", b"\x00\x00\x01\x00"),
        "/favicon.png": ("image/png", b"\x89PNG\r\n\x1a\n"),
        "/apple-touch-icon.png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    }

    for path, (content_type, signature) in expected.items():
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"] == content_type
        assert response.headers["cache-control"] == "public, max-age=3600"
        assert response.content.startswith(signature)
