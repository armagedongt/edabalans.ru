import os
import re
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
    assert nav.links == ["https://похудение-это-есть.рф/", "https://похудение-это-есть.рф/lk", destination, "https://похудение-это-есть.рф/blog", "https://t.me/FitnessSergey", "https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw"]
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
        assert f'src="https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/{path}"' in response.text


@pytest.mark.parametrize("path,mime", [("404-fragment.html", "text/html"), ("404.js", "application/javascript"), ("shrug-character-v1.svg", "image/svg+xml")])
def test_tilda_assets_are_public_and_cors_enabled(path, mime):
    response = TestClient(app).get("/public-site-errors/" + path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(mime)
    assert response.headers["access-control-allow-origin"] == "*"
    if path == "404-fragment.html":
        assert "{{" not in response.text
        assert "<iframe" not in response.text


def test_members_moved_preview_and_legacy_paths_use_approved_card():
    client = TestClient(app)
    response = client.get("/preview/members-moved", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.headers["cache-control"] == "no-store"
    assert '<meta name="robots" content="noindex,nofollow">' in response.text
    assert "Личный кабинет переехал" in response.text
    assert "я отправил вам на почту письмо с новым паролем" in response.text
    normalized = response.text.lower()
    assert re.search(r"\bмы\b", normalized) is None
    assert "tilda" not in normalized
    assert "тильд" not in normalized
    assert 'href="/public-site-assets/soft-sky-sunrise-background.css"' in response.text
    assert 'class="ed-moved ed-soft-sky-sunrise-background"' in response.text
    assert 'href="https://похудение-это-есть.рф/lk"' in response.text
    assert 'href="https://t.me/FitnessSergey"' in response.text
    assert 'href="https://max.ru/u/' in response.text
    assert "{{" not in response.text

    legacy = client.get("/members/courses/old-course-code/material", headers={"Accept": "text/html"})
    assert legacy.status_code == 404
    assert "Личный кабинет переехал" in legacy.text
    assert "я отправил вам на почту письмо с новым паролем" in legacy.text


def test_members_moved_background_is_a_reusable_public_asset():
    response = TestClient(app).get("/public-site-assets/soft-sky-sunrise-background.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert response.headers["access-control-allow-origin"] == "*"
    assert ".ed-soft-sky-sunrise-background" in response.text
    assert "radial-gradient" in response.text


@pytest.mark.parametrize("path", ["/members", "/members/login", "/members/signup/group/unseen-group", "/members/courses/unseen-course/nested/material.html", "/upgrade", "/hello", "/page118942576.html", "/period"])
def test_all_legacy_member_paths_show_the_same_card_without_redirect(path):
    response = TestClient(app).get(path + "?token=private-marker", headers={"Accept": "text/html"}, follow_redirects=False)
    assert response.status_code == 404
    assert "location" not in response.headers
    assert "Личный кабинет переехал" in response.text
    assert "private-marker" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/payment", "/payment_5900", "/payment_7900", "/payment_9800", "/payment_all"])
def test_legacy_manual_payment_links_serve_existing_form_directly(path):
    client = TestClient(app)
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 200
    assert "location" not in response.headers
    assert response.content == client.get("/pay").content
