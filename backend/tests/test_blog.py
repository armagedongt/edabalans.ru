from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.blog_content import load_blog_catalog
from app.blog_routes import router


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_blog_home_is_public_and_uses_manifest_cards() -> None:
    response = client.get("/blog")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "Похудение — это есть.рф" in response.text
    assert "Авторский блог Сергея Воронцова" in response.text
    assert (
        "Пишу о питании, похудении и пищевых привычках, "
        "чтобы сделать ваше похудение проще."
    ) in response.text
    assert response.text.count('class="article-card"') == 6
    assert response.text.count('class="card-tag"') == 6
    assert 'data-category-filter="Личное"' in response.text
    assert 'data-category-filter="ЗОЖ"' in response.text
    assert 'id="articles-title"' not in response.text
    assert "/articles/skolko-vremeni-nuzhno-na-pohudenie" in response.text
    assert "site-footer.js" in response.text
    assert "/blog/assets/blog.css" in response.text


def test_blog_home_trailing_slash_is_supported() -> None:
    assert client.get("/blog/").status_code == 200


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
    assert 'class="toc-dock"' in response.text
    assert 'data-component="blog-cta"' in response.text
    assert 'data-tracking-key="blog_intensive"' in response.text
    assert "blog_cta(" not in response.text
    assert response.text.count('class="article-card"') == 3
    assert '<meta property="og:type" content="article">' in response.text


def test_unknown_blog_article_returns_404() -> None:
    assert client.get("/blog/articles/not-a-real-article").status_code == 404


def test_blog_assets_and_fonts_are_whitelisted() -> None:
    font = client.get("/blog/fonts/inter-cyrillic.woff2")
    stylesheet = client.get("/blog/assets/blog.css")
    photo = client.get("/blog/assets/sergey-author.png")

    assert font.status_code == 200
    assert font.headers["content-type"] == "font/woff2"
    assert font.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/png"
    assert client.get("/blog/fonts/unknown.woff2").status_code == 404
    assert client.get("/blog/assets/unknown.js").status_code == 404


def test_blog_media_is_manifest_whitelisted() -> None:
    media = client.get("/blog/media/13277231/01.png")

    assert media.status_code == 200
    assert media.headers["content-type"] == "image/png"
    assert media.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/blog/media/not-declared.svg").status_code == 404


def test_blog_is_indexable_and_sitemap_lists_all_articles() -> None:
    robots = client.get("/blog/robots.txt")
    sitemap = client.get("/blog/sitemap.xml")

    assert robots.status_code == 200
    assert "Allow: /" in robots.text
    assert "Disallow" not in robots.text
    assert "https://blog.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/sitemap.xml" in robots.text
    assert sitemap.status_code == 200
    assert sitemap.headers["content-type"].startswith("application/xml")
    assert sitemap.text.count("<url>") == 7
    assert "/articles/nepriyatnaya-pravda-pro-med" in sitemap.text


def test_every_published_article_and_declared_image_is_served() -> None:
    catalog = load_blog_catalog()

    assert len(catalog.published) == 6
    for article in catalog.published:
        page = client.get(f"/blog/articles/{article.slug}")
        assert page.status_code == 200
        assert page.text.count('data-component="blog-cta"') == 1
        assert page.text.count('class="article-card"') == 3
        assert '<img src="http' not in page.text
        assert page.text.count(f'<figure><img src="/blog/media/{article.hero.file}"') == 1
        for media_name in (article.hero.file, *article.media):
            media = client.get(f"/blog/media/{media_name}")
            assert media.status_code == 200
            assert media.headers["content-type"].startswith("image/")
