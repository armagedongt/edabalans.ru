import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.blog_content import load_blog_catalog
from app.blog_routes import router
from app.database import Base, get_db


app = FastAPI()
app.include_router(router)
engine = create_engine(
    "sqlite+pysqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
factory = sessionmaker(bind=engine, expire_on_commit=False)


def override_db():
    with factory() as db:
        yield db


app.dependency_overrides[get_db] = override_db
client = TestClient(app)


def test_blog_pagination_selection_in_javascript() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the isolated JavaScript pagination test")
    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_name("blog-pagination.test.cjs"))],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_blog_home_is_public_and_uses_manifest_cards() -> None:
    response = client.get("/blog")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "Похудение — это есть.рф" in response.text
    assert "Блог Сергея Воронцова" in response.text
    assert response.text.index('<h1 id="blog-title">') < response.text.index(
        '<p class="eyebrow">Блог Сергея Воронцова</p>'
    )
    hero = response.text.split('<section class="shell hero"', 1)[1].split('</section>', 1)[0]
    hero_copy = hero.split('<div class="hero-copy">', 1)[1].split('</div>', 1)[0]
    assert 'class="categories"' not in hero_copy
    assert hero.index('class="hero-photo"') < hero.index('class="categories"')
    assert (
        "Пишу о питании, похудении и пищевых привычках, "
        "чтобы сделать ваше похудение проще."
    ) in response.text
    published_count = len(load_blog_catalog().published)
    assert response.text.count('class="article-card"') == published_count
    assert response.text.count('class="card-tag"') == published_count
    first_card = response.text.split('class="article-card"', 1)[1].split('</article>', 1)[0]
    assert first_card.index('class="card-visual"') < first_card.index('class="card-tag"')
    assert first_card.index('class="card-tag"') < first_card.index('class="card-title"')
    assert "Ответ на вопрос о сроках либо поставит жирный крест" in response.text
    assert (
        "На фотографии — Брайан Джонсон. В 47 лет предприниматель называл себя "
        "самым здоровым человеком на планете и тратил огромные деньги на проект "
        "Blueprint: анализы, режим, оборудование и попытку замедлить старение."
    ) in response.text
    assert 'data-category-filter="Личное"' in response.text
    assert 'data-category-filter="Ну, типа... ЗОЖ"' in response.text
    assert 'data-category-filter="ЗОЖ"' not in response.text
    expected_health_count = sum(
        article.category == "Ну, типа... ЗОЖ" for article in load_blog_catalog().published
    )
    assert response.text.count('data-category="Ну, типа... ЗОЖ"') == expected_health_count
    assert 'id="articles-title"' not in response.text
    assert "/articles/skolko-vremeni-nuzhno-na-pohudenie" in response.text
    assert f'/blog/media/{load_blog_catalog().published[0].card.file}' in response.text
    assert 'loading="eager" decoding="async" fetchpriority="high"' in hero
    assert response.text.count('loading="lazy" decoding="async"') >= 6
    assert "site-footer.js" in response.text
    assert "https://edabalans.ru/cookie-notice.js" in response.text
    assert "/blog/assets/blog.css" in response.text
    assert 'href="https://похудение-это-есть.рф/intensive">Бесплатный интенсив</a>' in response.text
    assert 'href="https://похудение-это-есть.рф/">Мастер-класс</a>' in response.text
    assert '>Главная</a>' not in response.text
    assert 'class="brand-icon"' not in response.text
    assert 'class="nav-intensive"' not in response.text
    public_header = response.text.split('<header class="site-header site-header--public">', 1)[1].split("</header>", 1)[0]
    assert public_header.index('>Блог</a>') < public_header.index('>Мастер-класс</a>')
    assert public_header.index('>Мастер-класс</a>') < public_header.index('>Бесплатный интенсив</a>')
    assert public_header.index('>Бесплатный интенсив</a>') < public_header.index('class="nav-contact"')
    assert 'class="nav-contact-trigger"' in response.text
    assert 'href="#contacts">Контакты</a>' not in response.text
    assert 'href="https://t.me/FitnessSergey"' in response.text
    assert 'href="https://max.ru/id230409966750_biz"' in response.text


def test_blog_home_trailing_slash_is_supported() -> None:
    assert client.get("/blog/").status_code == 200


def test_favicon_test_pages_are_isolated_and_noindex() -> None:
    expected = {
        "black": ("Блог — чёрная П.", "favicon-test-black.svg"),
        "blue": ("Личный кабинет — синяя П.", "favicon-test-blue.svg"),
        "face": ("Главная — фотография", "favicon-test-face.png"),
    }

    for variant, (title, favicon) in expected.items():
        response = client.get(f"/blog/favicon-tests/{variant}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert f"<title>{title}</title>" in response.text
        assert '<meta name="robots" content="noindex, nofollow">' in response.text
        assert f'/blog/assets/{favicon}?v=20260831a' in response.text
        assert "article-card" not in response.text

    assert client.get("/blog/favicon-tests/unknown").status_code == 404


def test_blog_article_has_toc_cta_metadata_and_related_cards() -> None:
    response = client.get("/blog/articles/skolko-vremeni-nuzhno-na-pohudenie")

    assert response.status_code == 200
    assert "Сколько времени нужно на похудение?" in response.text
    assert (
        '<link rel="canonical" '
        'href="https://blog.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/'
        'articles/skolko-vremeni-nuzhno-na-pohudenie">'
    ) in response.text
    assert 'class="toc-mobile"' in response.text
    assert '<details class="toc-mobile"><summary>Содержание</summary>' in response.text
    assert 'class="toc-dock"' in response.text
    assert "В этом материале" in response.text
    assert 'data-component="blog-cta"' in response.text
    assert 'data-tracking-key="blog_intensive"' in response.text
    assert 'href="https://похудение-это-есть.рф/intensive"' in response.text
    assert "Как сделать похудение проще" in response.text
    assert "Читать бесплатно" in response.text
    assert '<header class="article-hero">' in response.text
    assert "https://edabalans.ru/cookie-notice.js" in response.text
    article_hero = response.text.split('<header class="article-hero">', 1)[1].split("</header>", 1)[0]
    assert "<p>" not in article_hero
    assert "blog_cta(" not in response.text
    assert response.text.count('class="article-card"') == 3
    assert '<meta property="og:type" content="article">' in response.text
    assert 'loading="eager" decoding="async" fetchpriority="high"' in article_hero
    assert 'loading="lazy" decoding="async"' in response.text
    assert 'href="https://похудение-это-есть.рф/intensive">Бесплатный интенсив</a>' in response.text
    assert 'href="https://похудение-это-есть.рф/">Мастер-класс</a>' in response.text
    assert '>Главная</a>' not in response.text
    assert 'class="brand-icon"' not in response.text
    assert 'class="nav-intensive"' not in response.text
    assert 'class="nav-contact-trigger"' in response.text


def test_unknown_blog_article_returns_404() -> None:
    assert client.get("/blog/articles/not-a-real-article").status_code == 404


def test_blog_assets_and_fonts_are_whitelisted() -> None:
    font = client.get("/blog/fonts/inter-cyrillic.woff2")
    stylesheet = client.get("/blog/assets/blog.css")
    script = client.get("/blog/assets/blog.js")
    photo = client.get("/blog/assets/sergey-author.png")
    black_favicon = client.get("/blog/assets/favicon-test-black.svg")
    blue_favicon = client.get("/blog/assets/favicon-test-blue.svg")
    face_favicon = client.get("/blog/assets/favicon-test-face.png")

    assert font.status_code == 200
    assert font.headers["content-type"] == "font/woff2"
    assert font.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith(("text/javascript", "application/javascript"))
    assert re.search(r"\.hero h1 \{[^}]*font-weight: 800;[^}]*\}", stylesheet.text)
    assert re.search(r"\.hero-photo img \{[^}]*object-position: center;[^}]*transform: none;[^}]*\}", stylesheet.text)
    assert re.search(
        r"\.categories button \{[^}]*border-radius: 7px;[^}]*background: color-mix[^}]*\}",
        stylesheet.text,
    )
    assert re.search(r"\.categories button:hover, \.categories button\.active \{[^}]*background: var\(--blue\);[^}]*\}", stylesheet.text)
    assert re.search(r"\.card-tag \{[^}]*border-radius: 7px;[^}]*background: var\(--cloud\);[^}]*\}", stylesheet.text)
    assert re.search(r"\.card-copy \{[^}]*overflow: hidden;[^}]*-webkit-line-clamp: 4;[^}]*\}", stylesheet.text)
    assert re.search(r"\.theme-toggle:hover \{[^}]*border-color: var\(--blue\);[^}]*color: var\(--blue\);[^}]*\}", stylesheet.text)
    assert re.search(r"\.header-inner \{[^}]*grid-template-columns: minmax\(215px, 1fr\) auto minmax\(215px, 1fr\);[^}]*\}", stylesheet.text)
    assert re.search(r"\.nav \{[^}]*justify-content: center;[^}]*\}", stylesheet.text)
    assert re.search(r"\.brand strong \{[^}]*font-size: 15px;[^}]*font-weight: 800;[^}]*\}", stylesheet.text)
    assert ".nav > .nav-intensive" not in stylesheet.text
    assert re.search(r"\.article-layout \{[^}]*width: min\(760px, 100%\);[^}]*\}", stylesheet.text)
    assert re.search(r"\.article-hero \{[^}]*width: min\(760px, 100%\);[^}]*\}", stylesheet.text)
    assert re.search(r"\.toc-dock \{[^}]*position: fixed;[^}]*\}", stylesheet.text)
    assert 'writing-mode: vertical-rl' not in stylesheet.text
    mobile_rules = re.search(r"@media \(max-width: 900px\) \{(.*?)\n\}", stylesheet.text, re.DOTALL)
    assert mobile_rules is not None
    assert re.search(r"\.toc-dock \{[^}]*display: none;[^}]*\}", mobile_rules.group(1))
    assert re.search(r"\.toc-mobile \{[^}]*display: block;[^}]*\}", mobile_rules.group(1))
    assert "mobileToc.open = false" in script.text
    assert "document.getElementById(decodeURIComponent(link.getAttribute('href').slice(1)))" in script.text
    assert ".filter(Boolean)" in script.text
    assert "window.addEventListener('scroll', updateTocCurrent" in script.text
    assert "setAttribute('aria-current', 'location')" in script.text
    assert "removeAttribute('aria-current')" in script.text
    assert "setMobileNavOpen" in script.text
    assert "setContactOpen" in script.text
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/png"
    assert black_favicon.status_code == 200
    assert black_favicon.headers["content-type"] == "image/svg+xml"
    assert blue_favicon.status_code == 200
    assert blue_favicon.headers["content-type"] == "image/svg+xml"
    assert face_favicon.status_code == 200
    assert face_favicon.headers["content-type"] == "image/png"
    assert client.get("/blog/assets/brain-logo.png").status_code == 404
    assert client.get("/blog/fonts/unknown.woff2").status_code == 404
    assert client.get("/blog/assets/unknown.js").status_code == 404


def test_blog_media_is_manifest_whitelisted() -> None:
    media = client.get("/blog/media/13277231/01.png")

    assert media.status_code == 200
    assert media.headers["content-type"] == "image/png"
    assert media.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/blog/media/not-declared.svg").status_code == 404


def test_shared_article_styles_and_local_manrope_are_served() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    article_page = client.get("/blog/articles/pohudenie-nachinaetsya-ne-s-pohudeniya")
    assert article_page.status_code == 200
    assert 'id="article"' in article_page.text
    for shared_style in ("article-typography.css", "article-note.css"):
        assert f'href="/blog/assets/{shared_style}?v=' in article_page.text
    for public_name, source_name in (
        ("article-typography.css", "typography.css"),
        ("article-note.css", "note.css"),
    ):
        response = client.get(f"/blog/assets/{public_name}")
        assert response.status_code == 200
        assert response.content == (root / "content/article-components" / source_name).read_bytes()
    for name in ("manrope-cyrillic.woff2", "manrope-latin.woff2"):
        response = client.get(f"/blog/fonts/{name}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "font/woff2"
    image = client.get("/blog/assets/sergey-author-v2.webp")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/webp"


def test_obsolete_bot_test_removed_but_author_banner_preserved() -> None:
    page = client.get("/blog/articles/pohudenie-nachinaetsya-ne-s-pohudeniya")
    assert "Тест о комфорте похудения в меню бота" not in page.text
    assert "Сергей Воронцов: похудеть быстро или навсегда" in page.text


def test_blog_is_indexable_and_sitemap_lists_all_articles() -> None:
    robots = client.get("/blog/robots.txt")
    sitemap = client.get("/blog/sitemap.xml")

    assert robots.status_code == 200
    assert "Allow: /" in robots.text
    assert "Disallow" not in robots.text
    assert "https://blog.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/sitemap.xml" in robots.text
    assert sitemap.status_code == 200
    assert sitemap.headers["content-type"].startswith("application/xml")
    assert sitemap.text.count("<url>") == len(load_blog_catalog().published) + 1
    assert "/articles/nepriyatnaya-pravda-pro-med" in sitemap.text


def test_every_published_article_and_declared_image_is_served() -> None:
    catalog = load_blog_catalog()
    media_root = Path(__file__).resolve().parents[2] / "content" / "blog" / "media"

    assert {
        "tilda-49734795", "tilda-49745867", "tilda-67280331"
    }.issubset({article.source_id for article in catalog.published})
    for article in catalog.published:
        page = client.get(f"/blog/articles/{article.slug}")
        assert page.status_code == 200
        assert page.text.count('data-component="blog-cta"') == 1
        assert page.text.count('class="article-card"') == 3
        assert '<img src="http' not in page.text
        expected_hero_count = 1 if article.hero.show else 0
        header = page.text.split('<header class="article-hero">', 1)[1].split("</header>", 1)[0]
        assert header.count(f'<figure><img src="/blog/media/{article.hero.file}"') == expected_hero_count
        for media_name in (article.hero.file, article.card.file, *article.media):
            media = client.get(f"/blog/media/{media_name}")
            assert media.status_code == 200
            assert media.headers["content-type"].startswith("image/")
            with Image.open(media_root / media_name) as image:
                image.load()


def test_confirmed_static_batch_is_published_and_excluded_stories_are_not_public() -> None:
    catalog = load_blog_catalog()
    slugs = {article.slug for article in catalog.published}
    batch_sources = {
        "skrytye-zapory-i-banalnyy-syuzhet": "11277666",
        "dieta-sryv-i-matematika": "11494317",
        "eti-dolbannye-10000-shagov": "11522121",
        "professionalnyy-edok": "11762932",
        "net-vremeni-obyasnyat-prosto-hudey": "12296286",
        "poterya-myshc-pri-pohudenii": "13436070",
        "tri-oshibki-v-nachale-pohudeniya": "13785403",
        "sdelat-pohudenie-proshche": "14021584",
        "hodit-chtoby-hudet": "14102926",
        "hochesh-hudet-esh-kartoshku": "14183275",
        "pravila-bezopasnosti-za-shvedskim-stolom": "12857458",
        "mozhno-li-pit-vo-vremya-edy": "693339",
        "saharozamenitel-vyzyvaet-rak-net": "Sahar-09-18",
        "glikemicheskiy-indeks-eto-lishnee": "11207593",
        "pp-recepty-eto-ploho": "10999474",
        "kak-nachat-trenirovki-i-ne-brosit": "training-combined-2023",
        "a-mne-trener-posovetoval": "12922345",
    }
    expected_hashes = {
        "skrytye-zapory-i-banalnyy-syuzhet": ["9bbf1c9374b9c7a9a5f5f9ceaeb7d8d55985fb2f6dfdaa26d94654704a5863dd"],
        "dieta-sryv-i-matematika": ["09ad28646f33c4e34f15ce4566c4bdd092adc1ddd78348cedeee841c3a8fd658"],
        "eti-dolbannye-10000-shagov": ["9b9b7a865b5a677cb2e4fd704430e8f12a69f38f0e06aa97377707f0472756dc"],
        "professionalnyy-edok": ["8b625d7d786701ad63e81ca099c4073d8033357ba77a0d7ed111b5ec1a37990b"],
        "net-vremeni-obyasnyat-prosto-hudey": ["823dc29029a91e77d5381a555032e07705e96655836f0ae6f2274c029e0ea472"],
        "poterya-myshc-pri-pohudenii": ["4e3814f7cee4e83dc55a057c792abc7dd474097e4614714ffe1466b50459e17a"],
        "tri-oshibki-v-nachale-pohudeniya": ["457f4c8a48924fd3109cd16966d0579e45d8e615052efd03b62f1a0f87a0ce2e"],
        "sdelat-pohudenie-proshche": ["6319472e05580b33dc89c50c6424331cda81f7613f4df777112f3ba2935bf3f0"],
        "hodit-chtoby-hudet": ["ca7d25a7f226b91cc7e9bbec93a6de91ac5bc6880432678a237c7d4be5f463e5"],
        "hochesh-hudet-esh-kartoshku": ["38d590cc78fd16c4d05346ae858f8fbf24dcdc89e4f723c1a4d5560cfcf5f6dd"],
        "pravila-bezopasnosti-za-shvedskim-stolom": ["3d32d1cfe629a3a3be89644ea93475560261bafe4099d43c5926f53b2186984f"],
        "mozhno-li-pit-vo-vremya-edy": ["05c62f3079c14cfd5f2e4514c047fe17e736a777f650aed805dfb506bcca4959"],
        "saharozamenitel-vyzyvaet-rak-net": ["67375ce6b528b13aa57d1b355ef9f8bf41d158e494dafa469287d7410c30f9b0"],
        "glikemicheskiy-indeks-eto-lishnee": ["4c59de85bd33069c63f2685397519e4206c92af98989542098af2fee21d0daa7"],
        "pp-recepty-eto-ploho": ["6ca7aba7ecfec08012fba0f6c0122ce4ad4b4236f2d06905a91856c82f615796"],
        "kak-nachat-trenirovki-i-ne-brosit": [
            "d87212723d4f9bf04cb92867d4749d22341101c514f639f864604b5da0935d83",
            "da4d597d0b51a33ef928c9e795bb7bf948dfcacbb96efe06adbac03fdb3415e9",
            "0461943da5f9f65ea7081e79bee747167e762f53a4dbb560a58aae56b47ab148",
        ],
        "a-mne-trener-posovetoval": ["eb757031d04c7e9c8b3f8d0bd51a8acc869fe3ce2a4173259880c9b785be0c9c"],
    }
    expected_urls = {
        "skrytye-zapory-i-banalnyy-syuzhet": ["https://pikabu.ru/story/skryityie_zaporyi_i_banalnyiy_syuzhet_vozmozhno_u_vas_tozhe_11277666"],
        "dieta-sryv-i-matematika": ["https://pikabu.ru/story/dieta_sryiv_i_matematika_11494317"],
        "eti-dolbannye-10000-shagov": ["https://pikabu.ru/story/yeti_dolbannyie_10_000_shagov_11522121"],
        "professionalnyy-edok": ["https://pikabu.ru/story/professionalnyiy_edok_11762932"],
        "net-vremeni-obyasnyat-prosto-hudey": ["https://pikabu.ru/story/net_vremeni_obyasnyat_prosto_khudey_12296286"],
        "poterya-myshc-pri-pohudenii": ["https://pikabu.ru/story/poterya_myishts_pri_pokhudenii_13436070"],
        "tri-oshibki-v-nachale-pohudeniya": ["https://pikabu.ru/story/tri_oshibki_v_nachale_pokhudeniya_13785403"],
        "sdelat-pohudenie-proshche": ["https://pikabu.ru/story/sdelat_pokhudenie_proshche_14021584"],
        "hodit-chtoby-hudet": ["https://pikabu.ru/story/khodit_chtobyi_khudet_14102926"],
        "hochesh-hudet-esh-kartoshku": ["https://pikabu.ru/story/khochesh_khudet_zatknis_i_esh_kartoshku_14183275"],
        "pravila-bezopasnosti-za-shvedskim-stolom": ["https://pikabu.ru/story/pravila_bezopasnosti_za_shvedskim_stolom_12857458"],
        "mozhno-li-pit-vo-vremya-edy": ["https://vc.ru/flood/693339-tak-mozhno-pit-vo-vremya-edy-ili-net-a-vsuhomyatku-tochno-vredno"],
        "saharozamenitel-vyzyvaet-rak-net": ["https://telegra.ph/Sahar-09-18"],
        "glikemicheskiy-indeks-eto-lishnee": ["https://pikabu.ru/story/glikemicheskiy_indeks__yeto_lishnee_11207593"],
        "pp-recepty-eto-ploho": ["https://pikabu.ru/story/pp_retseptyi__yeto_plokho_i_vot_pochemu_10999474"],
        "kak-nachat-trenirovki-i-ne-brosit": [
            "https://pikabu.ru/story/otvet_na_post_chellendzh_30_dney_bega_2_den_10276321",
            "https://pikabu.ru/story/kak_nachat_trenirovki_i_ne_brosit_chellendzhinstruktsiya_10779442",
            "https://vc.ru/flood/752179-8-sovetov-tem-kto-hochet-nachat-begat",
        ],
        "a-mne-trener-posovetoval": ["https://pikabu.ru/story/a_mne_trener_posovetoval_12922345"],
    }

    assert batch_sources.keys() <= slugs
    excluded_slugs = {
        "kak-ya-100000-shagov-reshil-proyti",
        "kak-sdelat-celnozernovoy-ris-sedobnym",
        "dva-sousa-krasnoe-i-beloe",
    }
    assert excluded_slugs.isdisjoint(slugs)
    for slug in excluded_slugs:
        assert client.get(f"/blog/articles/{slug}").status_code == 404
    excluded_source_ids = {
        "10197439",
        "11528528",
        "11553382",
        "CHernovik-08-18-3",
        "Dva-sousa-Krasnoe-i-beloe-03-18",
    }
    assert excluded_source_ids.isdisjoint({article.source_id for article in catalog.published})
    manifest_path = Path(__file__).resolve().parents[2] / "content" / "blog" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    published_provenance_ids = {
        str(source_id)
        for article in manifest["articles"]
        if article["status"] == "published"
        for source_id in article.get("source_provenance", {}).get("external_ids", [])
    }
    assert excluded_source_ids.isdisjoint(published_provenance_ids)
    manifest_by_slug = {article["slug"]: article for article in manifest["articles"]}
    for slug, source_id in batch_sources.items():
        article = manifest_by_slug[slug]
        assert article["source_id"] == source_id
        provenance = article["source_provenance"]
        if slug == "kak-nachat-trenirovki-i-ne-brosit":
            assert provenance["external_ids"] == ["10276321", "10779442", "752179"]
        else:
            assert provenance["external_ids"] == [source_id]
        assert provenance["urls"] == expected_urls[slug]
        assert provenance["sha256"] == expected_hashes[slug]
        assert provenance["source_basis"] == "full_source"
        assert provenance["validation_status"] == "pass"
        assert provenance["review_status"] == "pass"
    diet = catalog.by_slug("dieta-sryv-i-matematika")
    assert diet is not None
    assert diet.hero.file != diet.card.file
    assert "exact source" in diet.hero.provenance


def test_semaglutide_article_is_published_unchanged() -> None:
    catalog = load_blog_catalog()
    slug = "ukolol-i-pohudel-ozempik-semavik-nyuansy"
    article = catalog.by_slug(slug)
    assert article is not None
    assert article in catalog.published
    assert article.source_id == "13327360"
    assert article.category == "Похудение"
    assert article.hero.file == "13327360/01.webp"
    assert article.hero.show is False
    assert article.card.file == "13327360/01.webp"
    assert article.card.fit == "contain"

    page = client.get(f"/blog/articles/{slug}")
    header = page.text.split('<header class="article-hero">', 1)[1].split("</header>", 1)[0]
    assert "13327360/01.webp" not in header
    assert '<img src="/blog/media/13327360/01.webp"' in page.text
    assert 'property="og:image" content="https://blog.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/blog/media/13327360/01.webp"' in page.text

    catalog_page = client.get("/blog")
    assert (
        'class="card-image card-image--contain" src="/blog/media/13327360/01.webp"'
        in catalog_page.text
    )

    manifest_path = Path(__file__).resolve().parents[2] / "content" / "blog" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_by_slug = {article["slug"]: article for article in manifest["articles"]}
    provenance = manifest_by_slug[slug]["source_provenance"]
    assert provenance["source_basis"] == "full_source"
    assert provenance["validation_status"] == "pass"
    assert provenance["review_status"] == "pass"

    semaglutide_path = Path(__file__).resolve().parents[2] / "content" / "blog" / "articles" / "13327360.md"
    semaglutide_body = semaglutide_path.read_text(encoding="utf-8").split("\nblog_cta(", 1)[0].rstrip()
    assert hashlib.sha256(semaglutide_body.encode("utf-8")).hexdigest() == (
        "ef8ef0dd424f8aea82ac22794f65a0e3aa431edb78e97a8c2d6a5f6b8b71eb98"
    )


def test_manifest_card_fit_is_rendered_without_destructive_crop() -> None:
    catalog = load_blog_catalog()
    article = catalog.by_slug("temperatura-vody-dlya-priema-vnutr")
    assert article is not None
    assert article.card.fit == "contain"
    page = client.get("/blog")
    assert (
        f'class="card-image card-image--contain" src="/blog/media/{article.card.file}"'
        in page.text
    )
