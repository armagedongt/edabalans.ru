import os
import struct

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
BASE = "/assets/strength-tutorial/"


def test_published_tutorial_and_all_illustrations_are_served() -> None:
    for name, content_type in (
        ("index.html", "text/html"),
        ("tutorial.css", "text/css"),
        ("tutorial.js", "text/javascript"),
        ("content.json", "application/json"),
    ):
        response = client.get(BASE + name)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(content_type)
    payload = client.get(BASE + "content.json").json()
    assert len(payload["screens"]) == 7
    for photo in payload["illustrations"].values():
        response = client.get(BASE + photo["src"])
        assert response.status_code == 200, photo["src"]
        assert response.headers["content-type"].startswith("image/png")
        width, height = struct.unpack(">II", response.content[16:24])
        assert (width, height) == (photo["width"] * 3, photo["height"] * 3)


def test_tutorial_asset_route_rejects_unknown_and_outside_files() -> None:
    for path in ("missing.png", "images/unknown.png", "../apps/strength.html", "%2e%2e%2f.env"):
        assert client.get(BASE + path).status_code == 404
