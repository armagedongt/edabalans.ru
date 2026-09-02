import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.intensive_public_cta import INTENSIVE_PUBLIC_CTA  # noqa: E402
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
        self.block_image_source_order: dict[str, list[str]] = {}
        self.image_source_order: list[str] = []
        self.iframe_sources: set[str] = set()
        self.ids: list[str] = []
        self.main_count = 0
        self.block_order: list[str] = []
        self.block_fields: dict[str, set[str]] = {}
        self.block_field_counts: dict[str, dict[str, int]] = {}
        self.block_field_text: dict[str, dict[str, str]] = {}
        self.block_widths: dict[str, str | None] = {}
        self._block_stack: list[str | None] = []
        self._field_stack: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        parent_block = self._block_stack[-1] if self._block_stack else None
        parent_field = self._field_stack[-1] if self._field_stack else None
        block_id = attributes.get("data-homepage-block") or parent_block
        declared_block = attributes.get("data-homepage-block")
        declared_field = attributes.get("data-homepage-field")
        field_id = declared_field or parent_field
        if declared_block:
            self.block_order.append(declared_block)
            self.block_fields.setdefault(declared_block, set())
            self.block_widths[declared_block] = attributes.get("data-block-width")
        if block_id and declared_field:
            self.block_fields.setdefault(block_id, set()).add(field_id)
            counts = self.block_field_counts.setdefault(block_id, {})
            counts[field_id] = counts.get(field_id, 0) + 1
        if tag not in self.VOID_TAGS:
            self._block_stack.append(block_id)
            self._field_stack.append(field_id)
        if tag == "meta" and attributes.get("name") == "robots":
            self.content = attributes.get("content")
        if tag == "img" and attributes.get("src"):
            self.image_sources.add(attributes["src"])
            if block_id:
                self.block_image_source_order.setdefault(block_id, []).append(
                    attributes["src"]
                )
            self.image_source_order.append(attributes["src"])
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
            self._field_stack.pop()

    def handle_data(self, data: str) -> None:
        block_id = self._block_stack[-1] if self._block_stack else None
        field_id = self._field_stack[-1] if self._field_stack else None
        if block_id and field_id:
            fields = self.block_field_text.setdefault(block_id, {})
            fields[field_id] = fields.get(field_id, "") + data


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
    assert "box-shadow:0 2px 6px rgba(22,89,124,.31)" in response.text
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
    assert parser.iframe_sources == {
        "/preview/homepage-mobile/vsl-player.html?v=7"
    }
    assert (
        'data-media-src="/preview/homepage-mobile/vsl-player.html?'
        'v=7&context=anya-review"'
        in response.text
    )
    assert ".anya-slide--video{width:min(80vw,var(--anya-video-width,275px));aspect-ratio:1080/1914" in response.text
    assert "const anyaVideoAspect = 1080 / 1914;" in response.text
    assert "slider.style.setProperty('--anya-video-width', `${height * anyaVideoAspect}px`);" in response.text
    assert "/preview/homepage-mobile/media-coordinator.js?v=2" in response.text
    assert "const preloadDistance = Math.max(window.innerHeight, 640);" in response.text
    assert "frame.src = frame.dataset.mediaSrc;" in response.text
    assert "rootMargin: `0px 0px ${preloadDistance}px 0px`" in response.text
    assert {
        "/preview/homepage-mobile/crying-character.png",
        "/preview/homepage-mobile/final-cta-cat-clock.webp?v=2",
        "/preview/homepage-mobile/weight-loss-after-masterclass.svg",
        "/preview/homepage-mobile/weight-loss-before-masterclass.svg",
        "/preview/homepage-mobile/masterclass-inside-01.webp",
        "/preview/homepage-mobile/masterclass-inside-02.webp",
        "/preview/homepage-mobile/masterclass-inside-03.webp",
        "/preview/homepage-mobile/masterclass-inside-04.webp",
    }.issubset(parser.image_sources)
    for marker in (
        "Мастер-класс · 21 день",
        "Чтобы похудеть, нужно",
        "Выберите тариф",
        "Что случилось с Аней?",
        "Частые вопросы",
        "Вы долистали сайт до конца…",
        "Больше отзывов",
        "Всего через три недели у вас может быть повод написать что-то подобное",
        "Сайт использует cookie. Продолжая, вы принимаете",
        "Написать в ЛС в Telegram",
        "Написать в ЛС в MAX",
        "Telegram-канал",
        "Канал в MAX",
    ):
        assert marker in response.text
    assert "Сомневаетесь? А вы сравните..." not in response.text
    assert (
        ".meme-card{position:relative;align-self:center;width:min(calc(100% + "
        "var(--final-inline) + var(--final-inline) - 28px),680px)"
        in response.text
    )
    assert INTENSIVE_PUBLIC_CTA["destination"] in response.text
    assert INTENSIVE_PUBLIC_CTA["button_label"] in response.text
    assert "{{INTENSIVE_PUBLIC_CTA_" not in response.text
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
        ".reviews-after-cat{width:min(var(--content-frame),"
        "calc(100% - var(--page-gutter) - var(--page-gutter)))"
        in response.text
    )
    assert (
        ".anya-story__header{width:min(var(--content-frame),"
        "calc(100% - var(--page-gutter) - var(--page-gutter)))"
        in response.text
    )
    assert (
        ".anya-story__slider{position:relative;width:min(calc(100% - "
        "max(var(--page-gutter),calc((100% - var(--content-frame))/2))),"
        "var(--content-standard-max))"
        in response.text
    )
    assert (
        ".anya-story__after{width:min(var(--content-frame),"
        "calc(100% - var(--page-gutter) - var(--page-gutter)))"
        in response.text
    )
    assert (
        "#edb-pricing-neurozeh-v1 .edb-pricing-intro {\n"
        "      width: min(100%, 430px);"
        in response.text
    )
    assert (
        "#edb-pricing-neurozeh-v1 .edb-pricing-intro {\n"
        "        width: 100%;\n        max-width: none;"
        in response.text
    )
    assert (
        "width: min(100%, calc(var(--content-standard-max) + 64px));"
        in response.text
    )
    assert "grid-column: 1;\n        grid-row: 2;" in response.text
    assert (
        "width: min(100%, calc(var(--content-wide) + 64px));"
        in response.text
    )
    assert "grid-column: auto;\n        grid-row: auto;" in response.text
    assert (
        ".pain:not(.pain--final){background:rgba(255,255,255,.90);"
        "color:rgb(31,34,38);font-weight:700}"
        in response.text
    )
    assert "box-shadow:0 2px 6px rgba(22,89,124,.31)" in response.text
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
    assert parser.block_order.index("reviews-voice") < parser.block_order.index(
        "reviews-featured"
    ) < parser.block_order.index("experience-proof") < parser.block_order.index(
        "anya-heading"
    )
    assert parser.block_order.index("reviews-after-cat") < parser.block_order.index(
        "reviews-wall"
    ) < parser.block_order.index("footer") < parser.block_order.index("cookie-notice")
    assert 'data-cookie-notice' in response.text
    assert 'data-cookie-dismiss' in response.text
    assert 'class="desktop-contact__trigger"' in response.text
    assert (
        'aria-expanded="false" aria-haspopup="true" '
        'aria-controls="desktop-contact-panel"'
        in response.text
    )
    assert 'href="https://t.me/FitnessSergey"' in response.text
    assert 'href="https://t.me/Fitness_Talks"' in response.text
    assert response.text.count('href="https://max.ru/id230409966750_biz"') == 2
    assert "@media (min-width: 900px) and (max-width: 1179px)" in response.text
    assert 'class="mobile-contact__trigger"' in response.text
    assert 'aria-controls="mobile-contact-panel"' in response.text
    assert "contactTrigger.addEventListener('click'" in response.text
    assert "if (!contact.contains(event.target)) setOpen(false);" in response.text
    assert "if (event.key !== 'Escape' || panel.hidden) return;" in response.text
    assert '>Приемлемо</button>' in response.text
    assert '>политику обработки персональных данных</a>.' in response.text
    assert (
        ".cookie-notice__copy a { color: inherit; font-weight: inherit; "
        "text-decoration: underline;"
        in response.text
    )
    assert "padding: 28px 0 24px;" in response.text
    overlay_rule = response.text.split(
        "#edb-pricing-neurozeh-v1 .edb-product-overlay {", 1
    )[1].split("}", 1)[0]
    overlay_lock_rule = response.text.split(
        "html.edb-product-overlay--locked body {", 1
    )[1].split("}", 1)[0]
    overlay_layer_rule = response.text.split(
        ".chain-block--pricing.has-open-overlay {", 1
    )[1].split("}", 1)[0]
    overlay_back_rule = response.text.split(
        "#edb-pricing-neurozeh-v1 .edb-product-overlay-back {", 1
    )[1].split("}", 1)[0]
    overlay_cta_rule = response.text.split(
        "#edb-pricing-neurozeh-v1 .edb-product-overlay-cta {", 1
    )[1].split("}", 1)[0]
    assert "overflow-y: auto;" in overlay_rule
    assert "overscroll-behavior: contain;" in overlay_rule
    assert (
        "html.edb-product-overlay--locked,\n"
        "    html.edb-product-overlay--locked body {"
        in response.text
    )
    assert "overflow: hidden;" in overlay_lock_rule
    assert "z-index: 1200;" in overlay_layer_rule
    assert "background: #26afff;" in overlay_back_rule
    assert "background: var(--site-orange);" in overlay_cta_rule
    assert "document.documentElement.classList.add('edb-product-overlay--locked');" in response.text
    assert "document.documentElement.classList.remove('edb-product-overlay--locked');" in response.text
    assert "pricingSection.classList.add('has-open-overlay');" in response.text
    assert "pricingSection.classList.remove('has-open-overlay');" in response.text
    assert "button.addEventListener('click', () => openProduct(button.dataset.product));" in response.text
    assert "root.querySelector('.edb-product-overlay-back').addEventListener('click', closeOverlay);" in response.text
    assert "pricingStack.append(basicPlan, consultPlan);" in response.text
    assert ".edb-pricing-plan:last-child" not in response.text
    assert "width:min(calc(100% + 5px),805px)" in response.text
    assert "gap:calc(clamp(10px,3vw,18px) + 5px)" in response.text
    assert "scrollbar-color: #7ed2ff #eefaff;" in response.text
    assert "scroll-behavior: smooth;" in response.text
    assert "html { scroll-behavior: auto; }" in response.text
    assert "html::-webkit-scrollbar-thumb" in response.text
    assert "display: inline-flex; height: 40px; align-items: center; justify-content: center;" in response.text
    assert ".desktop-wordmark { padding-left: 12px;" in response.text
    assert ".site-title { margin-top: 42px; }" in response.text
    assert "notice.hidden = true;" in response.text
    assert "background: var(--site-blue);" in response.text
    assert "background: rgba(255,255,255,.83);" in response.text
    assert "box-shadow: 0 4px 8px -4px rgba(17,142,216,.55);" in response.text
    assert (
        "box-shadow: 0 6px 12px -6px rgba(22,104,157,.42), "
        "0 2px 5px rgba(22,104,157,.1);"
        in response.text
    )
    assert (
        "width: min(560px,calc(100% - var(--page-gutter) - "
        "var(--page-gutter)));"
        in response.text
    )
    assert "background: linear-gradient(135deg,#49c5ff" not in response.text
    assert parser.block_image_source_order["reviews-featured"] == [
        "https://optim.tildacdn.com/tild3462-3461-4633-b639-613964313736/-/format/webp/Frame_492445363_1.jpg.webp",
        "https://optim.tildacdn.com/tild6336-3032-4033-b434-613563326139/-/format/webp/Frame_492445372_1.jpg.webp",
        "https://optim.tildacdn.com/tild6238-3062-4138-b234-336662303539/-/contain/758x1058/center/center/-/format/webp/Frame_492445364_2.jpg.webp",
        "https://optim.tildacdn.com/tild6634-6636-4463-b361-663039303138/-/format/webp/__29_1.jpg.webp",
    ]
    assert parser.block_image_source_order["reviews-wall"] == [
        "https://optim.tildacdn.com/tild3133-3832-4464-b037-623236633763/-/resize/600x600/-/format/webp/__1.jpg.webp",
        "https://optim.tildacdn.com/tild3438-6233-4630-a533-336566346264/-/resize/600x600/-/format/webp/__2.jpg.webp",
        "https://optim.tildacdn.com/tild3537-6466-4733-a337-623831303937/-/resize/600x600/-/format/webp/__3.jpg.webp",
        "https://optim.tildacdn.com/tild3763-3332-4166-b234-326266323263/-/resize/600x600/-/format/webp/__4.jpg.webp",
        "https://optim.tildacdn.com/tild3562-3438-4937-a663-386133663562/-/resize/600x600/-/format/webp/__6.jpg.webp",
        "https://optim.tildacdn.com/tild3038-3638-4630-b132-616433356430/-/resize/600x600/-/format/webp/__7.jpg.webp",
        "https://optim.tildacdn.com/tild3635-3435-4565-b535-313163343663/-/resize/600x600/-/format/webp/__8.jpg.webp",
        "https://optim.tildacdn.com/tild6630-6530-4236-a638-343130303032/-/resize/600x600/-/format/webp/__28.jpg.webp",
        "https://optim.tildacdn.com/tild3363-3531-4861-b430-383064316239/-/resize/600x600/-/format/webp/__21.jpg.webp",
        "https://optim.tildacdn.com/tild6339-3131-4637-b335-623438313365/-/resize/600x600/-/format/webp/__22.jpg.webp",
        "https://optim.tildacdn.com/tild3566-3132-4161-b964-666430616538/-/resize/600x600/-/format/webp/__23.jpg.webp",
        "https://optim.tildacdn.com/tild6538-6330-4538-b766-343366643330/-/resize/600x600/-/format/webp/__24.jpg.webp",
        "https://optim.tildacdn.com/tild3734-3437-4164-b265-326365313164/-/resize/600x600/-/format/webp/__25.jpg.webp",
        "https://optim.tildacdn.com/tild3962-6238-4435-b935-326636626263/-/resize/600x600/-/format/webp/__26.jpg.webp",
        "https://optim.tildacdn.com/tild6635-3630-4165-a332-373434623264/-/resize/600x600/-/format/webp/__27.jpg.webp",
        "https://optim.tildacdn.com/tild3264-3637-4930-b066-613665343762/-/resize/600x600/-/format/webp/__1.jpg.webp",
        "https://optim.tildacdn.com/tild6661-3731-4966-a466-316131393864/-/resize/600x600/-/format/webp/__2.jpg.webp",
        "https://optim.tildacdn.com/tild3065-6139-4561-b334-643739396331/-/resize/600x600/-/format/webp/__3.jpg.webp",
        "https://optim.tildacdn.com/tild3861-3865-4437-b330-313263383230/-/resize/600x600/-/format/webp/__4.jpg.webp",
        "https://optim.tildacdn.com/tild3263-3566-4161-a438-313262653237/-/resize/600x600/-/format/webp/__5.jpg.webp",
        "https://optim.tildacdn.com/tild3933-6339-4537-b036-656633366263/-/resize/600x600/-/format/webp/__6.jpg.webp",
    ]
    assert response.text.count('class="reviews-featured__item"') == 4
    assert response.text.count('class="reviews-wall__item"') == 21
    assert "const seconds = 12.8" in response.text
    assert "URL.createObjectURL" in response.text
    assert "const playButton = widget.querySelector('[data-voice-play]')" in response.text
    assert "const uploadButton = widget.querySelector('[data-voice-upload]')" in response.text
    assert "const fileInput = widget.querySelector('[data-voice-file]')" in response.text
    assert "const seek = widget.querySelector('[data-voice-seek]')" in response.text
    assert "playButton.addEventListener('click', async () =>" in response.text
    assert "uploadButton.addEventListener('click', () => fileInput.click())" in response.text
    assert "fileInput.addEventListener('change', () =>" in response.text
    assert "seek.addEventListener('input', () =>" in response.text
    assert "audio.addEventListener('play', () =>" in response.text
    assert "audio.addEventListener('pause', () =>" in response.text
    assert "pointerStart" in response.text
    assert "event.key === 'ArrowRight'" in response.text
    assert 'class="review-lightbox__cta-button" href="#pricing"' in response.text
    assert "ctaButton.addEventListener('click', () => close({ restoreFocus: false }))" in response.text
    block_map_path = Path(__file__).parents[2] / "content/public-site/homepage/block-map.json"
    block_map = json.loads(block_map_path.read_text(encoding="utf-8"))
    assert parser.block_order == [block["id"] for block in block_map["blocks"]]
    for block in block_map["blocks"]:
        assert parser.block_fields[block["id"]] == set(block["fields"])
        assert parser.block_field_counts.get(block["id"], {}) == {
            field: 1 for field in block["fields"]
        }
        assert parser.block_widths[block["id"]] == block["width"]
        assert block["selector"] == f'[data-homepage-block="{block["id"]}"]'
    assert [block["order"] for block in block_map["blocks"]] == list(
        range(10, 10 * (len(block_map["blocks"]) + 1), 10)
    )
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


def test_homepage_reviews_preview_uses_playable_voice_featured_order_and_21_wall_reviews() -> None:
    response = client.get("/preview/homepage-reviews-wall")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    parser = RobotsMetaParser()
    parser.feed(response.text)
    expected_featured_sources = [
        "https://optim.tildacdn.com/tild3462-3461-4633-b639-613964313736/-/format/webp/Frame_492445363_1.jpg.webp",
        "https://optim.tildacdn.com/tild6336-3032-4033-b434-613563326139/-/format/webp/Frame_492445372_1.jpg.webp",
        "https://optim.tildacdn.com/tild6238-3062-4138-b234-336662303539/-/contain/758x1058/center/center/-/format/webp/Frame_492445364_2.jpg.webp",
        "https://optim.tildacdn.com/tild6634-6636-4463-b361-663039303138/-/format/webp/__29_1.jpg.webp",
    ]
    expected_tilda_asset_ids = [
        "tild3133-3832-4464-b037-623236633763",
        "tild3438-6233-4630-a533-336566346264",
        "tild3537-6466-4733-a337-623831303937",
        "tild3763-3332-4166-b234-326266323263",
        "tild3562-3438-4937-a663-386133663562",
        "tild3038-3638-4630-b132-616433356430",
        "tild3635-3435-4565-b535-313163343663",
        "tild6630-6530-4236-a638-343130303032",
        "tild3363-3531-4861-b430-383064316239",
        "tild6339-3131-4637-b335-623438313365",
        "tild3566-3132-4161-b964-666430616538",
        "tild6538-6330-4538-b766-343366643330",
        "tild3734-3437-4164-b265-326365313164",
        "tild3962-6238-4435-b935-326636626263",
        "tild6635-3630-4165-a332-373434623264",
        "tild3264-3637-4930-b066-613665343762",
        "tild6661-3731-4966-a466-316131393864",
        "tild3065-6139-4561-b334-643739396331",
        "tild3861-3865-4437-b330-313263383230",
        "tild3263-3566-4161-a438-313262653237",
        "tild3933-6339-4537-b036-656633366263",
    ]
    assert parser.block_image_source_order["reviews-featured"] == expected_featured_sources
    wall_sources = parser.block_image_source_order["reviews-wall"]
    promo_sources = [
        "/preview/homepage-mobile/reviews-promo-before-after.jpg?v=1",
        "/preview/homepage-mobile/reviews-promo-can-dont-want.jpg?v=1",
        "/preview/homepage-mobile/reviews-promo-cant-do.jpg?v=1",
        "/preview/homepage-mobile/reviews-promo-hudet-budem.jpg?v=1",
        "/preview/homepage-mobile/reviews-promo-time-cat.png?v=1",
    ]
    assert [wall_sources[index] for index in (2, 7, 12, 17, 22)] == promo_sources
    actual_tilda_asset_ids = [
        source.split("/")[3]
        for source in wall_sources
        if source.startswith("https://optim.tildacdn.com/")
    ]
    assert actual_tilda_asset_ids == expected_tilda_asset_ids
    assert response.text.count('class="reviews-featured__item"') == 4
    assert response.text.count('class="reviews-wall__item"') == 21
    assert response.text.count('class="reviews-wall__promo"') == 5
    wall_start = response.text.index('<section class="reviews-wall"')
    wall_end = response.text.index("</section>", wall_start)
    wall_markup = response.text[wall_start:wall_end]
    direct_child_tags = re.findall(r"^    <([a-z][\w-]*)\b", wall_markup, re.MULTILINE)
    assert direct_child_tags == [
        tag
        for review_index in range(1, 22)
        for tag in (
            ["button", "article"]
            if review_index in {2, 6, 10, 14, 18}
            else ["button"]
        )
    ]
    promo_positions = []
    search_from = wall_start
    for _ in range(5):
        search_from = response.text.index('class="reviews-wall__promo"', search_from)
        promo_positions.append(search_from)
        search_from += 1
    for promo_position, previous_review, next_review in zip(
        promo_positions,
        (2, 6, 10, 14, 18),
        (3, 7, 11, 15, 19),
        strict=True,
    ):
        assert response.text.index(
            f'data-review-index="{previous_review}"', wall_start
        ) < promo_position < response.text.index(
            f'data-review-index="{next_review}"', wall_start
        )
    assert all(source in response.text for source in promo_sources)
    assert "Давай не как в прошлый раз?" in response.text
    assert "Точно не хочешь?" in response.text
    assert "Давай помогу!" in response.text
    assert '<p class="reviews-wall__promo-copy">Ну... да!</p>' in response.text
    assert '<p class="reviews-wall__promo-copy">ПОРА!!!</p>' in response.text
    assert (
        '<a class="reviews-wall__promo-button" '
        'href="/preview/homepage-mobile#pricing">Начать прямо сейчас</a>'
        in response.text
    )
    assert response.text.count(
        'href="/preview/homepage-mobile#pricing">Начать прямо сейчас</a>'
    ) == 5
    assert "promoButton.href = './mobile.html#pricing'" in response.text
    assert "linear-gradient(145deg,#fff 0%,#fbfeff 55%,#f3fbff 100%)" in response.text
    assert "border-radius:clamp(7px,2vw,12px)" in response.text
    assert "border:1px solid rgba(132,205,239,.22)" in response.text
    assert "font-size:clamp(19px,5vw,34px)" in response.text
    assert "width:min(86%,190px)" in response.text
    assert "color:#52a9d8" in response.text
    assert "box-shadow:0 8px 12px -6px rgba(25,73,108,.4)" in response.text
    assert "background:linear-gradient(135deg,#ffd47d,#e8ae45)" in response.text
    assert "background:linear-gradient(135deg,#ff934f,#ffd47d)" in response.text
    assert 'data-homepage-block="reviews-voice"' in response.text
    assert response.text.count('class="voice-widget"') == 1
    assert 'data-voice-audio' in response.text
    assert 'data-voice-play' in response.text
    assert 'data-voice-upload' in response.text
    assert 'data-voice-file' in response.text
    assert 'data-voice-seek' in response.text
    assert 'accept="audio/*"' in response.text
    assert 'src="/blog/assets/favicon-test-face.png"' in response.text
    assert '<div class="voice-widget__author">Анна К.</div>' in response.text
    assert 'О том, что изменилось в питании и что стало проще в обычной жизни' in response.text
    assert 'О том, что изменилось в питании<br>' not in response.text
    assert 'тестовое аудио · нажмите на аватар, чтобы заменить' not in response.text
    assert "voice-widget__telegram" not in response.text
    assert "voice-widget__upload-badge" not in response.text
    assert "const seconds = 12.8" in response.text
    assert "URL.createObjectURL" in response.text
    assert "audio.play()" in response.text
    assert "fileInput.addEventListener('change'" in response.text
    assert "audio.addEventListener('error'" in response.text
    assert 'aria-valuetext="0:00 из 0:13"' in response.text
    assert 'aria-live="polite"' in response.text
    assert "seek.disabled = true" in response.text
    assert "seek.disabled = false" in response.text
    assert "--bubble-mask:" in response.text
    assert "margin-left:-8px" in response.text
    assert "-webkit-mask:var(--bubble-mask)" in response.text
    assert "mask:var(--bubble-mask)" in response.text
    assert "filter:drop-shadow(0 0 1.2px rgba(29,91,130,.24)) drop-shadow(0 4px 4.8px rgba(29,91,130,.18))" in response.text
    assert ".voice-widget__bubble::before" not in response.text
    assert "voice-widget__tail" not in response.text
    assert "viewBox='0 0 12 24'" in response.text
    assert "max-width:600px" in response.text
    assert "max-width:620px" in response.text
    assert "max-width:760px" in response.text
    assert 'class="telegram-chat"' not in response.text
    assert 'data-homepage-block="reviews-featured"' in response.text
    assert 'data-review-index="1"' in response.text
    assert 'data-review-index="21"' in response.text
    assert 'data-review-index="22"' not in response.text
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in response.text
    assert "--reviews-wall-gap:clamp(10px,3vw,18px)" in response.text
    assert "wall.dataset.layout = 'ordered-masonry'" in response.text
    assert "column = promoIndex % 2" in response.text
    assert "const itemTop = Math.max(columnHeights[column], orderFloor)" in response.text
    assert "item.dataset.masonryColumn = String(column + 1)" in response.text
    assert "items.forEach((item) => resizeObserver.observe(item))" in response.text
    assert "transform:rotate(var(--tilt))" in response.text
    assert ".reviews-featured__item:nth-child(4){transform:translateY(-33%) rotate(var(--tilt))}" in response.text
    assert "filter:drop-shadow(0 5px 5px rgba(25,73,108,.23))" in response.text
    assert ".reviews-wall__item{filter:drop-shadow(0 7px 7px rgba(25,73,108,.21))}" in response.text
    tilts = [
        float(value.removesuffix("deg"))
        for value in re.findall(r'style="--tilt:(-?\d*\.?\d+deg)"', response.text)
    ]
    assert len(tilts) == 30
    assert all(0 < abs(tilt) <= 2 for tilt in tilts)
    assert min(tilts) < 0 < max(tilts)
    assert "tild6131-3266-4736-b265-396265366664" not in response.text
    assert "tild6338-3130-4939-a335-653164356231" not in response.text
    assert "tild3438-6466-4063-b435-336239383962" not in response.text
    assert response.text.count('aria-label="Открыть отзыв ') == 21
    assert response.text.count('aria-label="Открыть избранный отзыв ') == 4
    assert 'data-review-lightbox role="dialog" aria-modal="true"' in response.text
    assert 'data-review-stage' in response.text
    assert 'data-review-prev' in response.text
    assert 'data-review-next' in response.text
    assert "stage.addEventListener('pointerdown'" in response.text
    assert "stage.addEventListener('pointerup'" in response.text
    assert "event.key === 'Escape'" in response.text
    assert "event.key === 'ArrowLeft'" in response.text
    assert "event.key === 'ArrowRight'" in response.text
    assert "wallSection.scrollIntoView" in response.text
    assert "const showSlide" in response.text
    assert "const continueAfterWall" in response.text
    assert 'data-review-promo hidden' in response.text
    assert "wall: [...document.querySelector('[data-homepage-block=\"reviews-wall\"]')" in response.text
    assert "trigger.classList.contains('reviews-wall__promo')" in response.text
    assert "promo.removeAttribute('data-masonry-column')" in response.text
    assert "promoHost.replaceChildren(promo)" in response.text
    assert "review-lightbox__cta" not in response.text
    assert "data-review-cta" not in response.text
    assert "const showCta" not in response.text
    assert '/preview/homepage-mobile/final-cta-cat-clock.webp?v=2' not in parser.image_sources
    assert "width:min(82vw,520px)" in response.text
    assert ".review-lightbox__prev{left:max(calc(50% - min(41vw,260px) + 8px)" in response.text
    assert ".review-lightbox__next{right:max(calc(50% - min(41vw,260px) + 8px)" in response.text


def test_homepage_vsl_uses_first_player_click_and_server_analytics() -> None:
    response = client.get("/preview/homepage-mobile/vsl-player.html")

    assert response.status_code == 200
    assert "boost: 7" in response.text
    assert "endpoint: '/api/public/video-analytics'" in response.text
    assert "previewVideo.currentTime = 0" in response.text
    assert "analyticsApi.markEngaged()" in response.text
    assert "mvp--controls-hidden" in response.text
    assert "mvp-card-wave" in response.text
    assert "setTimeout(()=>root.classList.add('mvp--controls-hidden'), 1000)" in response.text
    assert "Рассказываю кое-что интересное" not in response.text
    assert response.text.count("Нажмите, чтобы включить звук") == 1
    autoplay_setup = response.text.split("if (MODULES.autoplay) {", 1)[1].split(
        "} else {", 1
    )[0]
    assert "previewVideo.loop = true;" in autoplay_setup
    assert "if (!passiveAutoplayAllowed || soundEngaged) return;" in autoplay_setup
    assert "previewVideo.play().catch(()=>{});" in autoplay_setup
    assert "playAndTakeFocus" not in autoplay_setup
    sound_engagement = response.text.split("function enableSoundAndWatch(){", 1)[1].split(
        "\n  }", 1
    )[0]
    assert "soundEngaged = true;" in sound_engagement
    assert "previewVideo.loop = false;" in sound_engagement
    assert "soundCard.hidden = true;" in sound_engagement
    assert "announceActivePlayer();" in sound_engagement
    assert "prepareMainPlayback();" in sound_engagement
    assert "playAndTakeFocus(previewVideo, false);" in sound_engagement
    assert "showControls(true);" in sound_engagement
    active_player = response.text.split(
        "function playAndTakeFocus(target = video, announce = true){", 1
    )[1].split(
        "\n  }", 1
    )[0]
    assert "target.play();" in active_player
    assert "if (announce) announceActivePlayer();" in active_player
    assert "edabalans:player-active" in response.text
    assert "edabalans:pause-player" in response.text
    assert "event.source !== parent" in response.text
    pause_handler = response.text.split(
        "if (event.data?.type !== 'edabalans:pause-player') return;", 1
    )[1].split("\n  });", 1)[0]
    assert "passiveAutoplayAllowed = false;" in pause_handler
    assert "handoffPending = false;" in pause_handler
    assert "handoffAligning = false;" in pause_handler
    assert "previewVideo.removeEventListener('canplay', autoplayStart);" in pause_handler
    assert "videos.forEach(item=>item.pause());" in pause_handler
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
    anya_drag = response.text.split("if (PLAYER_CONTEXT === 'anya-review') {", 1)[1].split(
        "root.addEventListener('click', engageFromFirstPlayerClick, true);", 1
    )[0]
    assert "enableSoundAndWatch" not in anya_drag
    assert "homepage-anya-review-2026-09-01" in response.text
    assert "homepage-vsl-2026-09-02" in response.text
    assert "PLAYER_CONTEXT === 'anya-review'" in response.text
    assert "root.classList.toggle('mvp--anya-review', PLAYER_CONTEXT === 'anya-review');" in response.text
    assert "#modular-video-player.mvp--anya-review .mvp__video{inset:0;width:100%;height:100%;object-fit:contain}" in response.text
    assert (
        "const PLAYER_CONTEXT = new URLSearchParams(location.search).get('context') "
        "|| 'homepage-vsl';"
        in response.text
    )
    assert 'class="mvp__video mvp__video--preview"' in response.text
    assert 'class="mvp__video mvp__video--main" playsinline preload="none"' in response.text
    assert "mvp--awaiting-sound .mvp__controls" in response.text
    assert "mvp__loader" not in response.text
    media_presets = response.text.split("const MEDIA_PRESETS = {", 1)[1].split(
        "\n  };\n  const mediaPreset", 1
    )[0]
    assert "'homepage-vsl':" in media_presets
    assert "https://cdn-g.boomstream.com/balancer/3qGepzqy-9WmCBBoU.mp4" in media_presets
    assert "https://cdn-g.boomstream.com/balancer/F5zqt5iQ-9WmCBBoU.mp4" in media_presets
    assert "https://cdn-g.boomstream.com/balancer/IpVIy3yM-9WmCBBoU.mp4" in media_presets
    assert "https://cdn-g.boomstream.com/balancer/RkqYeVnc-9WmCBBoU.mp4" in media_presets
    anya_media_preset = media_presets.split("'anya-review': {", 1)[1].split(
        "\n    }", 1
    )[0]
    assert "volume:" not in anya_media_preset
    main_media_preset = media_presets.split("'homepage-vsl': {", 1)[1].split(
        "\n    }", 1
    )[0]
    assert "volume: 0.85" in main_media_preset
    assert "previewVideo.volume = mediaPreset.volume ?? 1;" in response.text
    assert "volumeSlider.value = String(video.volume);" in response.text
    assert "mainVideo.src = mediaPreset.source;" in response.text
    assert "previewVideo.addEventListener('ended'" in response.text
    assert "tryMainHandoff();" in response.text
    assert "attempt.then(activateMainVideo)" in response.text
    assert "const selectedVolume = previewVideo.volume;" in response.text
    assert "mainVideo.volume = selectedVolume;" in response.text
    assert "mainVideo.muted = selectedMuted;" in response.text
    assert "volumeSlider.value = mainVideo.muted ? '0'" in response.text
    assert "root.classList.add('mvp--handoff-pending');" in response.text
    assert "root.classList.remove('mvp--handoff-pending');" in response.text
    assert "mvp--handoff-pending .mvp__big-play" in response.text
    preview_handoff = response.text.split("previewVideo.addEventListener('ended', ()=>{", 1)[1].split(
        "});", 1
    )[0]
    assert "updatePlayUI();" not in preview_handoff
    assert "showControls(false);" not in preview_handoff
    assert "analyticsApi.trackTimeUpdate(item);" in response.text


def test_homepage_media_coordinator_pauses_other_audio_and_video() -> None:
    response = client.get("/preview/homepage-mobile/media-coordinator.js")

    assert response.status_code == 200
    assert "document.addEventListener('play'" in response.text
    assert "pauseLocalMedia(media);" in response.text
    assert "pauseOtherFrames();" in response.text
    assert "event.data?.type !== 'edabalans:player-active'" in response.text
    assert "event.data?.type === 'edabalans:player-idle'" in response.text
    assert "if (activeFrame === frame) activeFrame = null;" in response.text
    assert "pauseOtherFrames(frame);" in response.text
    anya_load = response.text.split("if (frame.dataset.mediaContext === 'anya-review') {", 1)[1].split(
        "return;", 1
    )[0]
    assert "if (!activeFrame) pauseOtherFrames(frame);" in anya_load
    assert "pauseFrame(frame);" not in anya_load
    assert "window.EdaMediaCoordinator = Object.freeze" in response.text


def test_homepage_uses_accepted_vsl_copy_without_editorial_placeholders() -> None:
    response = client.get("/preview/homepage-mobile")
    parser = RobotsMetaParser()
    parser.feed(response.text)

    for marker in (
        "За три недели научитесь делать ваше похудение — проще",
        "Вместо очередной голодовки",
        "А худеть как-то надо...",
        "Весь день держалась — вечером сорвалась",
        "Еда — единственное удовольствие",
        "Да, для похудения — нужен дефицит калорий.",
        "Вы будете вести дневник питания по фотографиям",
        "Мой подход",
        "Не ждите идеального момента или идеальных условий",
        "За моими плечами 600+ разобранных дневников питания",
        "Хотите познакомиться с моим подходом поближе?",
        "Обо мне",
        "Всего через три недели у вас может быть повод написать что-то подобное",
    ):
        assert marker in response.text
    for forbidden in (
        "Здесь будет короткий итог истории Ани.",
        "Лаааааадно...",
        "Вот вам еще отзывов!",
        "COPY SLOT",
        "DECISION",
        "DESIGN-QUESTION",
        "OFF-PAGE",
        "NOTE:",
        "Это примечание пока",
        "продолжение главного аргумента",
        "Как устроен Мастер-класс",
    ):
        assert forbidden not in response.text

    expected_fields = {
        "hero-intro": {
            "text": "За три недели научитесь делать ваше похудение — проще, а потом пользуйтесь этим всю жизнь!",
        },
        "hero-outro": {
            "paragraph-1": "Вместо очередной голодовки — я покажу вам со стороны ваше привычное питание и пищевые привычки.",
            "paragraph-2": "Вы научитесь лучше насыщаться за те же калории и соберете свою систему питания, в которой не нужно будет так много силы воли ради простого похудения.",
            "paragraph-3": "Я расскажу, что это за навыки, научу, как их освоить, покажу как применять и создам вокруг вас обстановку, чтобы эти навыки закрепились!",
        },
        "recognition-intro": {
            "html": "Казалось бы, слова вроде правильные... Но что если вы уже не можете есть ещё меньше, а двигаться больше — ну никак не получается? А худеть как-то надо...",
        },
        "recognition-scene": {
            "pain-1": "Весь день держалась — вечером сорвалась",
            "pain-2": "Ем и так мало — вес стоит",
            "pain-3": "Вроде похудела — вес опять вернулся",
            "pain-4": "Еда — единственное удовольствие",
            "pain-5": "Всё знаю — ничего не делаю...",
        },
        "recognition-explanation": {
            "paragraph-1": "Да, для похудения — нужен дефицит калорий. Но здоровое питание и пищевые привычки именно для того, чтобы у вас глаза на лоб не полезли от этого дефицита.",
            "paragraph-2": "Тяга к сладкому, частым перекусам, постоянный голод, невозможность вовремя остановиться, срывы и прочие оказии — это не ваши характеристики как личности, а просто недостаток навыков, как жить в дефиците калорий.",
        },
        "anya-outro": {
            "paragraph-1": "Не ждите идеального момента или идеальных условий, когда и на работе вдруг не будет стресса, и дома куда-то пропадут все домашние дела.",
            "paragraph-2": "Мы оба знаем, что этого не произойдет в обозримом будущем. И мы оба знаем, что с каждым годом худеть будет только тяжелее.",
        },
        "free-intensive": {
            "title": "Хотите познакомиться с моим подходом поближе?",
            "text": "Я записал бесплатный интенсив в четырёх частях «Последнее похудение», где я рассказываю как должна выглядеть история адекватного и успешного похудения от А до Я!",
            "cta": INTENSIVE_PUBLIC_CTA["button_label"],
        },
        "author": {
            "title": "Обо мне",
            "paragraph-1": "Топовый автор сообщества \"Мы Худеем\" на Pikabu.ru, велосипедист, триатлет (железный человек), путешественник, любитель тефтелей с чесноком и пюрешкой.",
            "paragraph-2": "Разок меня тоже бес попутал — набрал до 95кг. Потом одумался, поменял образ жизни и похудел до 70кг ни дня не сидя на диете и даже не зная, что существует приложение по учету калорий. С того времени 10 лет спокойно живу в новом весе и радуюсь жизни.",
        },
        "reviews-after-cat": {
            "title": "Больше отзывов",
            "text": "Всего через три недели у вас может быть повод написать что-то подобное 👇",
        },
    }
    for block_id, fields in expected_fields.items():
        actual = parser.block_field_text[block_id]
        for field_id, expected in fields.items():
            assert " ".join(actual[field_id].split()) == expected
    assert 'data-homepage-field="pain-6" aria-label="Я так больше не хочу."' in response.text

    approach_path = Path(__file__).parents[2] / "content/public-site/homepage/approach.md"
    approach = approach_path.read_text(encoding="utf-8")
    assert "Вместо ПП еды — **пищевые привычки**" in approach
    assert "Вместо подсчета граммов — **дневник по фото**" in approach
    assert "Вместо случайных попыток — понятный порядок действий" in approach
    assert "ПП-рецептов" not in approach


def test_homepage_mobile_preview_assets_are_public_noindex_and_allowlisted() -> None:
    assets = {
        "crying-character.png",
        "final-cta-cat-clock.webp",
        "max-full-colored-dark-official.png",
        "money-bag-ruble-v1.webp",
        "montserrat-cyrillic.woff2",
        "montserrat-latin.woff2",
        "media-coordinator.js",
        "masterclass-inside-01.webp",
        "masterclass-inside-02.webp",
        "masterclass-inside-03.webp",
        "masterclass-inside-04.webp",
        "reviews-promo-before-after.jpg",
        "reviews-promo-can-dont-want.jpg",
        "reviews-promo-cant-do.jpg",
        "reviews-promo-hudet-budem.jpg",
        "reviews-promo-time-cat.png",
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
