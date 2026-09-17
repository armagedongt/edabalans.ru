import os
from html.parser import HTMLParser

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.intensive_public_cta import INTENSIVE_PUBLIC_CTA


class Navigation(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "nav" and attrs.get("aria-label") == "Куда перейти":
            self.inside = True
        if tag == "a" and self.inside:
            self.links.append(attrs.get("href"))

    def handle_endtag(self, tag):
        if tag == "nav":
            self.inside = False


def test_browser_404_is_safe_not_indexable_and_uses_canonical_cta(monkeypatch):
    destination = "https://example.com/intensive?mode=free&source=canonical"
    monkeypatch.setitem(INTENSIVE_PUBLIC_CTA, "destination", destination)
    response = TestClient(app).get("/unknown-private-marker?E=secret-token-marker", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.headers["cache-control"] == "no-store"
    assert '<meta name="robots" content="noindex,nofollow">' in response.text
    assert "unknown-private-marker" not in response.text
    assert "secret-token-marker" not in response.text
    nav = Navigation()
    nav.feed(response.text)
    assert nav.links == ["https://похудение-это-есть.рф/", "https://похудение-это-есть.рф/lk", destination, "#ed404-contacts"]
    assert "data-edabalans-site-header" in response.text
    assert 'id="ed404-contacts" data-edabalans-site-footer' in response.text


@pytest.mark.parametrize("path", ["/api/no-such-route", "/admin/no-such-route", "/assets/missing", "/assets/missing.html", "/intensive/assets/day1/missing", "/intensive/assets/day1/missing.html", "/public-site-assets/missing", "/public-site-errors/missing", "/blog/assets/missing", "/missing.png", "/missing.js", "/preview/missing"])
def test_non_page_404_keeps_original_contract(path):
    response = TestClient(app).get(path, headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert not response.headers.get("content-type", "").startswith("text/html")


@pytest.mark.parametrize("accept", ["*/*", "application/json", "text/html;q=0", "text/html;q=invalid"])
def test_non_browser_accept_keeps_json(accept):
    response = TestClient(app).get("/unknown-page", headers={"Accept": accept})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_other_methods_and_non_404_responses_unchanged():
    client = TestClient(app)
    protected = client.get("/mcp/no-such-route", headers={"Accept": "text/html"})
    assert protected.status_code == 401
    assert not protected.headers.get("content-type", "").startswith("text/html")
    assert client.post("/unknown-page", headers={"Accept": "text/html"}).json() == {"detail": "Not Found"}
    response = client.post("/health", headers={"Accept": "text/html"})
    assert response.status_code == 405
    assert response.json() == {"detail": "Method Not Allowed"}
    assert client.get("/health").json() == {"status": "ok"}
    response = client.head("/unknown-page", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert response.content == b""
    assert response.headers["content-type"].startswith("text/html")


def test_404_on_legacy_host_loads_shared_assets_from_public_origin():
    response = TestClient(app, base_url="https://blog.example.com").get("/unknown-page", headers={"Accept": "text/html"})
    assert response.status_code == 404
    for path in ["site-header.js", "site-footer.js", "public-site-errors/shrug-character-v1.svg"]:
        assert f'src="https://edabalans.ru/{path}"' in response.text


@pytest.mark.parametrize("path,mime", [("404-fragment.html", "text/html"), ("404.js", "application/javascript"), ("shrug-character-v1.svg", "image/svg+xml")])
def test_tilda_assets_are_public_and_cors_enabled(path, mime):
    response = TestClient(app).get("/public-site-errors/" + path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(mime)
    assert response.headers["access-control-allow-origin"] == "*"
    if path == "404-fragment.html":
        assert "{{" not in response.text
        assert "<iframe" not in response.text
