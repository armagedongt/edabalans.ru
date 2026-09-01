import json
import os
from html.parser import HTMLParser
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


client = TestClient(app)


class RobotsMetaParser(HTMLParser):
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.content: str | None = None
        self.image_sources: set[str] = set()
        self.iframe_sources: set[str] = set()
        self.ids: list[str] = []
        self.main_count = 0
        self.block_order: list[str] = []
        self.block_fields: dict[str, set[str]] = {}
        self.block_widths: dict[str, str | None] = {}
        self._block_stack: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        parent_block = self._block_stack[-1] if self._block_stack else None
        block_id = attributes.get("data-homepage-block") or parent_block
        declared_block = attributes.get("data-homepage-block")
        field_id = attributes.get("data-homepage-field")
        if declared_block:
            self.block_order.append(declared_block)
            self.block_fields.setdefault(declared_block, set())
            self.block_widths[declared_block] = attributes.get("data-block-width")
        if block_id and field_id:
            self.block_fields.setdefault(block_id, set()).add(field_id)
        if tag not in self.VOID_TAGS:
            self._block_stack.append(block_id)
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

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        block_id = attributes.get("data-homepage-block") or (
            self._block_stack[-1] if self._block_stack else None
        )
        field_id = attributes.get("data-homepage-field")
        if attributes.get("data-homepage-block"):
            self.block_order.append(attributes["data-homepage-block"])
            self.block_fields.setdefault(attributes["data-homepage-block"], set())
            self.block_widths[attributes["data-homepage-block"]] = attributes.get(
                "data-block-width"
            )
        if block_id and field_id:
            self.block_fields.setdefault(block_id, set()).add(field_id)

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.VOID_TAGS and self._block_stack:
            self._block_stack.pop()


def test_homepage_recognition_preview_is_public_and_noindex() -> None:
    response = client.get("/preview/homepage-recognition")
    source_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "homepage-preview"
        / "mobile.html"
    )
    source = source_path.read_text(encoding="utf-8")

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
    assert "/preview/homepage-mobile/crying-character.png" in parser.image_sources
    assert parser.main_count == 1
    assert parser.iframe_sources == set()
    assert parser.image_sources == {
        "/preview/homepage-mobile/crying-character.png"
    }
    assert "data-public-faq" not in response.text
    assert 'id="site-footer"' not in response.text
    assert 'data-price-code=' not in response.text
    assert "data-recognition" in response.text
    assert 'data-library-block="recognition"' in response.text
    assert 'data-library-status="accepted"' in response.text
    assert "data-recognition-followup" in response.text
    assert "--recognition-media-gap:clamp(40px,6vw,56px)" in response.text
    assert "new URLSearchParams(location.search).get('cloud-shadow') === 'hard'" in response.text
    assert 'html[data-cloud-shadow="hard"] .pain:not(.pain--final)' in response.text
    assert "box-shadow:0 2px 6px rgba(22,89,124,.28)" in response.text
    assert "height:calc(var(--scene-height) + var(--animation-distance))" in response.text
    assert "Math.max(maxPainHeight+18,((laneHeight+maxPainHeight)/2)+8)" in response.text
    assert "(viewportHeight/2)-(field.offsetTop+(field.offsetHeight/2))" in response.text
    assert ".pain:not(.pain--final){width:1px;height:1px" in response.text
    assert "fetch('/api/public-site/content/approach'" in response.text
    for fragment_name in (
        "recognition",
        "recognition-script",
        "public-content-script",
    ):
        start_marker = f"<!-- library:{fragment_name}:start -->"
        end_marker = f"<!-- library:{fragment_name}:end -->"
        canonical_fragment = source.split(start_marker, 1)[1].split(end_marker, 1)[0]
        assert canonical_fragment.strip() in response.text
    assert not source_path.with_name("recognition.html").exists()


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
    assert (
        "/preview/homepage-mobile/vsl-player.html?v=3&context=anya-review"
        in parser.iframe_sources
    )
    assert {
        "/preview/homepage-mobile/crying-character.png",
        "/preview/homepage-mobile/final-cta-cat-clock.webp?v=2",
        "/preview/homepage-mobile/weight-loss-after-masterclass.svg",
        "/preview/homepage-mobile/weight-loss-before-masterclass.svg",
    }.issubset(parser.image_sources)
    for marker in (
        "Мастер-класс · 21 день",
        "Чтобы похудеть, нужно",
        "Выберите тариф",
        "Что случилось с Аней?",
        "Частые вопросы",
        "Вы долистали сайт до конца…",
        "Лаааааадно...",
        "Вот вам еще отзывов!",
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
    assert (
        'data-homepage-block="recognition-scene" data-block-width="content"'
        in response.text
    )
    assert "data-recognition-followup" in response.text
    assert "--recognition-media-gap:clamp(40px,6vw,56px)" in response.text
    assert (
        "height:calc(var(--scene-height) + var(--animation-distance))"
        in response.text
    )
    assert (
        "Math.max(maxPainHeight+18,((laneHeight+maxPainHeight)/2)+8)"
        in response.text
    )
    assert (
        "(viewportHeight/2)-(field.offsetTop+(field.offsetHeight/2))"
        in response.text
    )
    assert ".pain:not(.pain--final){width:1px;height:1px" in response.text
    assert "transform:translate3d(-50%,0,0)!important" in response.text
    assert 'data-anya-slider' in response.text
    assert 'data-anya-counter' not in response.text
    assert 'data-anya-prev' in response.text
    assert 'data-anya-next' in response.text
    assert 'class="anya-story__controls"' not in response.text
    assert "Видео Ани — временная медиазаглушка" not in response.text
    assert "Временное видео для проверки механики" not in response.text
    assert "document.body.dataset.anyaHint" not in response.text
    assert "document.body.dataset.anyaControls" not in response.text
    assert "document.body.dataset.playerFrame" not in response.text
    block_map_path = Path(__file__).parents[2] / "content/public-site/homepage/block-map.json"
    block_map = json.loads(block_map_path.read_text(encoding="utf-8"))
    assert parser.block_order == [block["id"] for block in block_map["blocks"]]
    for block in block_map["blocks"]:
        assert parser.block_fields[block["id"]] == set(block["fields"])
        assert parser.block_widths[block["id"]] == block["width"]
    assert "document.body.dataset.pricingTimer" not in response.text
    assert "document.body.dataset.pricingFill" not in response.text
    assert "document.body.dataset.supportTone" in response.text
    assert 'class="edb-pricing-timer"' not in response.text
    overlay_bar_rule = response.text.split(
        "#edb-pricing-neurozeh-v1 .edb-product-overlay-bar {", 1
    )[1].split("}", 1)[0]
    assert "position: fixed;" in overlay_bar_rule
    assert "bottom: 0;" in overlay_bar_rule
    assert "env(safe-area-inset-bottom)" in overlay_bar_rule


def test_homepage_vsl_uses_first_player_click_and_server_analytics() -> None:
    response = client.get("/preview/homepage-mobile/vsl-player.html")

    assert response.status_code == 200
    assert "boost: 7" in response.text
    assert "endpoint: '/api/public/video-analytics'" in response.text
    assert "video.currentTime = 0" in response.text
    assert "analyticsApi.markEngaged()" in response.text
    assert "mvp--controls-hidden" in response.text
    assert "mvp-card-wave" in response.text
    assert "setTimeout(()=>root.classList.add('mvp--controls-hidden'), 1000)" in response.text
    assert "Рассказываю кое-что интересное" not in response.text
    assert response.text.count("Нажмите, чтобы включить звук") == 1
    autoplay_setup = response.text.split("if (MODULES.autoplay) {", 1)[1].split(
        "} else {", 1
    )[0]
    assert "video.loop = true;" in autoplay_setup
    sound_engagement = response.text.split("function enableSoundAndWatch(){", 1)[1].split(
        "\n  }", 1
    )[0]
    assert "soundEngaged = true;" in sound_engagement
    assert "video.loop = false;" in sound_engagement
    assert "soundCard.hidden = true;" in sound_engagement
    assert "video.play().catch(()=>{});" in sound_engagement
    assert "showControls(true);" in sound_engagement
    first_player_click = response.text.split(
        "function engageFromFirstPlayerClick(event){", 1
    )[1].split("\n  }", 1)[0]
    assert "if (soundEngaged || event.button !== 0) return;" in first_player_click
    assert "event.preventDefault();" in first_player_click
    assert "event.stopImmediatePropagation();" in first_player_click
    assert "enableSoundAndWatch();" in first_player_click
    assert (
        "root.addEventListener('click', engageFromFirstPlayerClick, true);"
        in response.text
    )
    assert "soundCard.addEventListener('click', enableSoundAndWatch);" not in response.text
    assert "edabalans:video-play" not in response.text
    assert "Содержание" not in response.text
    assert "event.pointerType === 'mouse' && event.button !== 0" in response.text
    assert "homepage-anya-review-2026-09-01" in response.text
    assert "PLAYER_CONTEXT === 'anya-review'" in response.text
    assert (
        "const PLAYER_CONTEXT = new URLSearchParams(location.search).get('context') "
        "|| 'homepage-vsl';"
        in response.text
    )
    assert (
        'data-default-source="https://cdn-g.boomstream.com/balancer/'
        '5wlZSJxs-9WmCBBoU.mp4"'
        in response.text
    )
    media_presets = response.text.split("const MEDIA_PRESETS = {", 1)[1].split(
        "\n  };\n  const mediaPreset", 1
    )[0]
    assert "'homepage-vsl':" not in media_presets
    anya_media_preset = media_presets.split("'anya-review': {", 1)[1].split(
        "\n    }", 1
    )[0]
    assert "volume:" not in anya_media_preset
    main_media_preset = response.text.split(
        "const mediaPreset = MEDIA_PRESETS[PLAYER_CONTEXT] || {", 1
    )[1].split("\n  };", 1)[0]
    assert "volume: 0.85" in main_media_preset
    assert "video.volume = mediaPreset.volume ?? 1;" in response.text
    assert "volumeSlider.value = String(video.volume);" in response.text
    assert (
        "https://fast.vidalytics.com/video/x3JriQG2/JbSfK6ZK0K01YzRM/263820/"
        "243116__FFMPEG/mp4/video/480x270_h264_1000000/video.mp4"
        in response.text
    )


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
