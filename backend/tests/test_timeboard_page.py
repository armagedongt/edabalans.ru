import os
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")

from app.config import get_settings

get_settings.cache_clear()

from app.main import app


class PageResources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.urls.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.urls.append(values["href"])


def test_timeboard_redirect_and_page_resources_work_without_a_session() -> None:
    client = TestClient(app)
    redirect = client.get("/timeboard", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/timeboard/"

    page = client.get("/timeboard/")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert page.headers["referrer-policy"] == "no-referrer"
    resources = PageResources()
    resources.feed(page.text)
    assert len(resources.urls) == 2
    for url in resources.urls:
        response = client.get(f"/timeboard/{url}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
        assert response.headers["content-type"].startswith(
            "text/css" if url.endswith(".css") else ("text/javascript", "application/javascript")
        )


@pytest.mark.parametrize("name", ["README.md", "calendar.json", ".env", "app.js.map", "%2e%2e%2fconfig.py"])
def test_timeboard_cannot_serve_unlisted_files(name: str) -> None:
    assert TestClient(app).get(f"/timeboard/{name}").status_code == 404


def test_timeboard_has_no_server_write_endpoint() -> None:
    response = TestClient(app).post("/timeboard/", json={"title": "must stay in the browser"})
    assert response.status_code == 405
