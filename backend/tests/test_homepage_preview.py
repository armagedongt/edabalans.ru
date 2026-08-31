import os
from html.parser import HTMLParser

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


client = TestClient(app)


class RobotsMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.content: str | None = None
        self.image_sources: set[str] = set()
        self.iframe_sources: set[str] = set()
        self.ids: list[str] = []
        self.main_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "meta" and attributes.get("name") == "robots":
            self.content = attributes.get("content")
        if tag == "img" and attributes.get("src"):
            self.image_sources.add(attributes["src"])
        if tag == "iframe" and attributes.get("src"):
            self.iframe_sources.add(attributes["src"])
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        if tag == "main":
            self.main_count += 1


def test_homepage_recognition_preview_is_public_and_noindex() -> None:
    response = client.get("/preview/homepage-recognition")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    parser = RobotsMetaParser()
    parser.feed(response.text)
    assert parser.content is not None
    assert {value.strip() for value in parser.content.split(",")} == {
        "noindex",
        "nofollow",
    }
    assert "/preview/homepage-recognition/crying-character.png" in parser.image_sources
    assert "data-recognition" in response.text


def test_homepage_recognition_preview_image_is_public_and_noindex() -> None:
    response = client.get("/preview/homepage-recognition/crying-character.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in response.content[:32]
    assert b"IEND" in response.content[-32:]


def test_homepage_mobile_preview_contains_only_one_page_shell_and_accepted_blocks() -> None:
    response = client.get("/preview/homepage-mobile")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"

    parser = RobotsMetaParser()
    parser.feed(response.text)
    assert parser.content is not None
    assert {value.strip() for value in parser.content.split(",")} == {
        "noindex",
        "nofollow",
    }
    assert parser.main_count == 1
    assert len(parser.ids) == len(set(parser.ids))
    assert "/preview/homepage-mobile/vsl-player.html?v=2" in parser.iframe_sources
    assert {
        "/preview/homepage-mobile/crying-character.png",
        "/preview/homepage-mobile/final-cta-cat-clock.webp?v=2",
        "/preview/homepage-mobile/weight-loss-after-masterclass.svg",
        "/preview/homepage-mobile/weight-loss-before-masterclass.svg",
    }.issubset(parser.image_sources)
    for marker in (
        "Мастер-класс · 21 день",
        "Чтобы похудеть, нужно",
        "Выберите формат участия",
        "Что случилось с Аней?",
        "Частые вопросы",
        "Вы долистали сайт до конца…",
    ):
        assert marker in response.text
    assert '<body data-page-theme="blue-mist">' in response.text
    assert "page-theme-toolbar" not in response.text
    assert 'id="site-footer" data-edabalans-site-footer="public"' in response.text
    assert '[data-edabalans-site-footer]{position:relative;z-index:1;background:transparent;color:#17212b}' in response.text
    assert 'data-pricing-endpoint="/api/pricing/site/preview"' in response.text
    assert 'data-checkout-endpoint="/api/pricing/site/preview-checkout"' in response.text
    assert 'data-tilda-cart-url="https://похудение-это-есть.рф/"' in response.text
    assert "previewPricingCatalog" not in response.text
    assert "const productData" not in response.text
    assert "fetch('/api/public-site/content/faq'" in response.text
    assert "fetch('/api/public-site/content/approach'" in response.text
    assert 'data-anya-slider' in response.text


def test_homepage_vsl_uses_first_engagement_and_server_analytics() -> None:
    response = client.get("/preview/homepage-mobile/vsl-player.html")

    assert response.status_code == 200
    assert "boost: 7" in response.text
    assert "endpoint: '/api/public/video-analytics'" in response.text
    assert "video.currentTime = 0" in response.text
    assert "analyticsApi.markEngaged()" in response.text
    assert "mvp--controls-hidden" in response.text
    assert "Содержание" not in response.text


def test_homepage_mobile_preview_assets_are_public_noindex_and_allowlisted() -> None:
    assets = {
        "crying-character.png",
        "final-cta-cat-clock.webp",
        "max-full-colored-dark-official.png",
        "money-bag-ruble-v1.webp",
        "montserrat-cyrillic.woff2",
        "montserrat-latin.woff2",
        "vsl-player.html",
        "weight-loss-after-masterclass.svg",
        "weight-loss-before-masterclass.svg",
    }

    for asset_name in assets:
        response = client.get(f"/preview/homepage-mobile/{asset_name}")
        assert response.status_code == 200, asset_name
        assert response.headers["cache-control"] == "no-cache", asset_name
        assert response.headers["x-robots-tag"] == "noindex, nofollow", asset_name
        assert response.content, asset_name

    assert client.get("/preview/homepage-mobile/../app_routes.py").status_code == 404
    assert client.get("/preview/homepage-mobile/not-allowlisted.svg").status_code == 404
