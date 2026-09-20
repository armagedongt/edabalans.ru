from __future__ import annotations

from html import escape
import json
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from app.blog_content import (
    BLOG_CATEGORIES,
    BLOG_PUBLIC_ORIGIN,
    card_html,
    load_blog_catalog,
    related_cards_html,
    render_article_body,
    toc_html,
)
from app.blog_draft_routes import optional_blog_admin, owner_cards_html, PRIVATE_HEADERS
from app.blog_draft_service import public_payload, render_article
from app.database import get_db
from sqlalchemy.orm import Session


router = APIRouter()
BLOG_DIR = Path(__file__).resolve().parent / "static" / "blog"
BLOG_FONT_FILES = {"inter-cyrillic.woff2", "inter-latin.woff2", "manrope-cyrillic.woff2", "manrope-latin.woff2"}
BLOG_ARTICLE_STYLES = {"article-typography.css": "typography.css", "article-note.css": "note.css"}
BLOG_ASSET_FILES = {
    "blog.css",
    "blog.js",
    "draft-editor.css",
    "draft-editor.js",
    "favicon-test-black.svg",
    "favicon-test-blue.svg",
    "favicon-test-face.png",
    "sergey-author.png",
    "sergey-author-v2.webp",
}
FAVICON_TEST_PAGES = {
    "black": ("Блог — чёрная П.", "favicon-test-black.svg"),
    "blue": ("Личный кабинет — синяя П.", "favicon-test-blue.svg"),
    "face": ("Главная — фотография", "favicon-test-face.png"),
}
FAVICON_TEST_VERSION = "20260831a"
def _template(name: str) -> str:
    return (BLOG_DIR / name).read_text(encoding="utf-8")


def _html_response(value: str) -> HTMLResponse:
    response = HTMLResponse(value)
    response.headers["Cache-Control"] = "no-cache"
    return response


@router.get("/blog", include_in_schema=False)
@router.get("/blog/", include_in_schema=False)
def blog_home(
    identity: str | None = Depends(optional_blog_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    catalog = load_blog_catalog()
    categories = "".join(
        f'<li><button type="button" data-category-filter="{escape(category, quote=True)}">{escape(category)}</button></li>'
        for category in BLOG_CATEGORIES
    )
    rendered = (
        _template("index.html")
        .replace("<!-- BLOG_CATEGORIES -->", categories)
        .replace("<!-- BLOG_CARDS -->", "".join(card_html(article) for article in catalog.published))
        .replace("<!-- BLOG_OWNER_PANEL -->", owner_cards_html(db) if identity else "")
    )
    response = _html_response(rendered)
    if identity:
        response.headers.update(PRIVATE_HEADERS)
    return response


@router.get("/blog/favicon-tests/{variant}", include_in_schema=False)
def favicon_test_page(variant: str) -> HTMLResponse:
    page = FAVICON_TEST_PAGES.get(variant)
    if page is None:
        raise HTTPException(status_code=404, detail="favicon test page not found")
    title, favicon = page
    rendered = f"""<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <meta name=\"robots\" content=\"noindex, nofollow\">
  <title>{escape(title)}</title>
  <link rel=\"icon\" href=\"/blog/assets/{favicon}?v={FAVICON_TEST_VERSION}\">
</head>
<body></body>
</html>"""
    response = _html_response(rendered)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.get("/blog/articles/{slug}", include_in_schema=False)
def blog_article(slug: str, db: Session = Depends(get_db)) -> HTMLResponse:
    catalog = load_blog_catalog()
    article = catalog.by_slug(slug)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    published = public_payload(db, slug)
    body, toc = (
        render_article(slug, published, public=True)
        if published is not None
        else render_article_body(catalog, article)
    )
    canonical = f"{BLOG_PUBLIC_ORIGIN}/articles/{article.slug}"
    structured_data = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": article.title,
            "description": article.excerpt,
            "author": {"@type": "Person", "name": "Сергей Воронцов"},
            "mainEntityOfPage": canonical,
            "image": f"{BLOG_PUBLIC_ORIGIN}/blog/media/{article.hero.file}",
        },
        ensure_ascii=False,
    ).replace("</", r"<\/")
    replacements = {
        "{{TITLE}}": escape(article.title),
        "{{DESCRIPTION}}": escape(article.excerpt, quote=True),
        "{{CATEGORY}}": escape(article.category),
        "{{CANONICAL}}": escape(canonical, quote=True),
        "{{HERO_SRC}}": f"/blog/media/{escape(article.hero.file, quote=True)}",
        "{{HERO_ABSOLUTE}}": escape(
            f"{BLOG_PUBLIC_ORIGIN}/blog/media/{article.hero.file}", quote=True
        ),
        "{{HERO_ALT}}": escape(article.hero.alt, quote=True),
        "{{ARTICLE_BODY}}": body,
        "{{TOC_DESKTOP}}": toc_html(toc, mobile=False),
        "{{TOC_MOBILE}}": toc_html(toc, mobile=True),
        "{{RELATED_CARDS}}": related_cards_html(catalog, article),
        "{{STRUCTURED_DATA}}": structured_data,
    }
    rendered = _template("article.html")
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)
    return _html_response(rendered)


@router.get("/blog/sitemap.xml", include_in_schema=False)
def blog_sitemap() -> Response:
    catalog = load_blog_catalog()
    locations = [BLOG_PUBLIC_ORIGIN, *(f"{BLOG_PUBLIC_ORIGIN}/articles/{article.slug}" for article in catalog.published)]
    items = "".join(f"<url><loc>{escape(location)}</loc></url>" for location in locations)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'
    response = Response(xml, media_type="application/xml")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@router.get("/blog/robots.txt", include_in_schema=False)
def blog_robots() -> PlainTextResponse:
    value = f"User-agent: *\nAllow: /\nSitemap: {BLOG_PUBLIC_ORIGIN}/sitemap.xml\n"
    response = PlainTextResponse(value)
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@router.get("/blog/fonts/{font_name}", include_in_schema=False)
def blog_font(font_name: str) -> FileResponse:
    if font_name not in BLOG_FONT_FILES:
        raise HTTPException(status_code=404, detail="font not found")
    response = FileResponse(BLOG_DIR / "fonts" / font_name, media_type="font/woff2")
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@router.get("/blog/assets/{asset_name}", include_in_schema=False)
def blog_asset(asset_name: str) -> FileResponse:
    if asset_name in BLOG_ARTICLE_STYLES:
        path = Path(__file__).resolve().parents[2] / "content" / "article-components" / BLOG_ARTICLE_STYLES[asset_name]
        response = FileResponse(path, media_type="text/css")
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response
    if asset_name not in BLOG_ASSET_FILES:
        raise HTTPException(status_code=404, detail="asset not found")
    media_type = "image/webp" if asset_name.endswith(".webp") else mimetypes.guess_type(asset_name)[0] or "application/octet-stream"
    response = FileResponse(BLOG_DIR / "assets" / asset_name, media_type=media_type)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@router.get("/blog/media/{media_name:path}", include_in_schema=False)
def blog_media(media_name: str) -> FileResponse:
    catalog = load_blog_catalog()
    if media_name not in catalog.allowed_media:
        raise HTTPException(status_code=404, detail="media not found")
    media_path = catalog.content_dir / "media" / media_name
    media_type = "image/webp" if media_path.suffix.lower() == ".webp" else mimetypes.guess_type(media_name)[0]
    response = FileResponse(media_path, media_type=media_type)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
