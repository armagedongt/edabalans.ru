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


def test_primary_html_pages_reference_versioned_brand_icons() -> None:
    expected_links = (
        '<link rel="icon" type="image/png" href="/favicon.png?v=20260909c">',
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=20260909c">',
    )
    pages = (
        "/lk",
        "/intensive/",
        "/intensive/day-1",
        "/intensive/day-2",
        "/intensive/day-3",
        "/intensive/day-4",
    )

    for path in pages:
        response = client.get(path)
        assert response.status_code == 200
        for expected_link in expected_links:
            assert expected_link in response.text
