from __future__ import annotations

from html import escape
from dataclasses import replace
from datetime import datetime
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from app.blog_content import (
    BLOG_CATEGORIES,
    BLOG_PUBLIC_ORIGIN,
    blog_seo_title,
    card_html,
    load_blog_catalog,
    insert_inline_related,
    related_cards_html,
    render_article_body,
    toc_html,
)
from app.blog_draft_routes import optional_blog_admin, owner_cards_html, PRIVATE_HEADERS
from app.blog_draft_service import public_payload, published_card_overrides, published_description_overrides, render_article
from app.database import get_db
from app.blog_responsive_media import apply_responsive_images, derivative_files
from app.blog_reader_context import recognize_reader, reader_context
from app.config import get_settings
from sqlalchemy.orm import Session


router = APIRouter()


class ReaderRecognition(BaseModel):
    token: str = Field(min_length=1, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def safe_token_input(cls, value):
        token = value.get("token") if isinstance(value, dict) else None
        if isinstance(token, str):
            try:
                token.encode("utf-8")
            except UnicodeEncodeError:
                token = ""
        else:
            token = ""
        # Keep invalid input, including nested surrogates, out of JSON errors.
        return {"token": token}


@router.post("/blog/reader/recognize", include_in_schema=False)
def recognize_blog_reader(body: ReaderRecognition, request: Request, db: Session = Depends(get_db)):
    response = Response(status_code=204, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})
    if not recognize_reader(db, request, response, get_settings().app_auth_secret, body.token):
        raise HTTPException(400, "Персональная ссылка не подтверждена")
    return response


@router.get("/blog/reader/context", include_in_schema=False)
def blog_reader_context(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex"
    return reader_context(db, request, get_settings().app_auth_secret)


BLOG_DIR = Path(__file__).resolve().parent / "static" / "blog"
BLOG_PAGE_SIZE = 15
BLOG_FONT_FILES = {"inter-cyrillic.woff2", "inter-latin.woff2", "manrope-cyrillic.woff2", "manrope-latin.woff2"}
BLOG_ARTICLE_STYLES = {"article-typography.css": "typography.css", "article-note.css": "note.css"}
BLOG_ASSET_FILES = {
    "blog.css",
    "blog.js",
    "reader-navigation.css",
    "reader-navigation.js",
    "draft-editor.css",
    "draft-editor.js",
    "favicon-test-black.svg",
    "favicon-test-blue.svg",
    "favicon-test-face.png",
    "sergey-author.png",
    "sergey-author-v2.webp",
    "sergey-author-channel.webp",
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


def _public_catalog(db: Session):
    catalog = load_blog_catalog()
    descriptions = published_description_overrides(db)
    return replace(catalog, articles=tuple(
        replace(article, excerpt=descriptions.get(article.slug, article.excerpt))
        for article in catalog.articles
    ))


def _author() -> dict:
    return json.loads((BLOG_DIR.parents[3] / "content" / "blog" / "author.json").read_text(encoding="utf-8"))


def _person(author: dict) -> dict:
    url = BLOG_PUBLIC_ORIGIN + author["path"]
    return {"@type": "Person", "@id": url + "#person", "url": url,
            "name": author["name"], "jobTitle": author["role"], "description": author["description"],
            "image": BLOG_PUBLIC_ORIGIN + author["image"], "sameAs": author["same_as"]}


def _breadcrumbs(article=None) -> tuple[str, dict]:
    items = [("Блог", BLOG_PUBLIC_ORIGIN + "/")]
    if article is not None:
        items += [(article.category, BLOG_PUBLIC_ORIGIN + "/?" + urlencode({"category": article.category})),
                  (article.title, BLOG_PUBLIC_ORIGIN + "/articles/" + article.slug)]
    else:
        items.append(("Сергей Воронцов", BLOG_PUBLIC_ORIGIN + _author()["path"]))
    links = ' <span aria-hidden="true">/</span> '.join(
        f'<a href="{escape(url, quote=True)}">{escape(label)}</a>' if index < len(items) - 1
        else f'<span aria-current="page">{escape(label)}</span>'
        for index, (label, url) in enumerate(items)
    )
    data = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": index + 1, "name": label, "item": url}
        for index, (label, url) in enumerate(items)]}
    return f'<nav class="breadcrumbs" aria-label="Хлебные крошки">{links}</nav>', data


@router.get("/blog/author/sergey-vorontsov", include_in_schema=False)
def blog_author() -> HTMLResponse:
    author = _author()
    person = _person(author)
    breadcrumbs, breadcrumb_data = _breadcrumbs()
    body = (f'<div class="author-profile"><img class="author-profile-avatar" src="{escape(author["image"], quote=True)}" '
            f'alt="{escape(author["name"], quote=True)}" width="160" height="160"><div>'
            f'<p>{escape(author["role"])}</p><p>{escape(author["description"])}</p>'
            + ' · '.join(f'<a href="{escape(url, quote=True)}" rel="me">{label}</a>' for url, label in zip(author["same_as"], ("Telegram", "MAX")))
            + '</div></div>')
    template = re.sub(r'<section class="shell related-section".*?</section>', '', _template("article.html"), flags=re.S)
    replacements = {"{{TITLE}}": escape(author["name"]), "{{SEO_TITLE}}": escape(author["name"] + " — " + author["role"]),
                    "{{DESCRIPTION}}": escape(author["description"], quote=True), "{{CANONICAL}}": escape(person["url"], quote=True),
                    "{{HERO_ABSOLUTE}}": escape(person["image"], quote=True), "{{CATEGORY}}": "", "{{HERO}}": "",
                    "{{TOC_DESKTOP}}": "", "{{TOC_MOBILE}}": "", "{{ARTICLE_BODY}}": body,
                    "{{READER_NAVIGATION}}": "",
                    "{{BREADCRUMBS}}": breadcrumbs, "{{AUTHOR_BYLINE}}": "", "{{ARTICLE_DATES}}": "",
                    "{{BREADCRUMB_DATA}}": json.dumps({"@context": "https://schema.org", **breadcrumb_data}, ensure_ascii=False).replace("</", r"<\/"),
                    "{{STRUCTURED_DATA}}": json.dumps({"@context": "https://schema.org", "@type": "ProfilePage", "url": person["url"], "mainEntity": person}, ensure_ascii=False).replace("</", r"<\/")}
    rendered = re.sub(r"\{\{[A-Z_]+\}\}", lambda match: replacements.get(match.group(0), match.group(0)), template)
    return _html_response(rendered.replace('property="og:type" content="article"', 'property="og:type" content="profile"'))


@router.get("/blog", include_in_schema=False)
@router.get("/blog/", include_in_schema=False)
def blog_home(
    page: str = "1",
    category: str = "all",
    identity: str | None = Depends(optional_blog_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    catalog = _public_catalog(db)
    card_overrides = published_card_overrides(db)
    category = category if category in BLOG_CATEGORIES else "all"
    selected = tuple(article for article in catalog.published if category == "all" or article.category == category)
    page_count = max(1, (len(selected) + BLOG_PAGE_SIZE - 1) // BLOG_PAGE_SIZE)
    try:
        active_page = min(max(int(page), 1), page_count)
    except ValueError:
        active_page = 1

    def query(target_page: int = 1, target_category: str = category) -> str:
        params = {}
        if target_category != "all":
            params["category"] = target_category
        if target_page > 1:
            params["page"] = str(target_page)
        return urlencode(params)

    categories = "".join(
        f'<li><a href="?{escape(query(target_category=item), quote=True)}#articles" '
        f'data-category-filter="{escape(item, quote=True)}"'
        + (' class="active" aria-current="true"' if item == category else '')
        + f'>{escape("Все" if item == "all" else item)}</a></li>'
        for item in ("all", *BLOG_CATEGORIES)
    )
    pagination = "".join(
        f'<a class="page-link" href="?{escape(query(number), quote=True)}#articles"'
        + (' aria-current="page"' if number == active_page else '')
        + f'>{number}</a>'
        for number in range(1, page_count + 1)
    ) if page_count > 1 else ""
    if active_page < page_count:
        pagination += f'<a class="page-link next" rel="next" href="?{escape(query(active_page + 1), quote=True)}#articles">Следующая</a>'
    canonical = f"{BLOG_PUBLIC_ORIGIN}/" + (f"?{query(active_page)}" if query(active_page) else "")
    title = "Похудение — это есть · Авторский блог Сергея Воронцова"
    if category != "all":
        title += f" · {category}"
    if active_page > 1:
        title += f" · Страница {active_page}"
    rendered = (
        _template("index.html")
        .replace("{{CATALOG_CANONICAL}}", escape(canonical, quote=True))
        .replace("{{CATALOG_TITLE}}", escape(title))
        .replace("{{EMPTY_HIDDEN}}", "hidden" if selected else "")
        .replace("<!-- BLOG_PAGINATION -->", pagination)
        .replace("<!-- BLOG_CATEGORIES -->", categories)
        .replace(
            "<!-- BLOG_CARDS -->",
            "".join(
                card_html(
                    article,
                    card_file=card_overrides.get(article.slug, (article.card.file, article.card.fit))[0],
                    card_fit=card_overrides.get(article.slug, (article.card.file, article.card.fit))[1],
                )
                for article in selected[(active_page - 1) * BLOG_PAGE_SIZE:active_page * BLOG_PAGE_SIZE]
            ),
        )
        .replace("<!-- BLOG_OWNER_PANEL -->", owner_cards_html(db) if identity else "")
    )
    response = _html_response(apply_responsive_images(rendered, catalog.content_dir, catalog.allowed_media))
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
    catalog = _public_catalog(db)
    card_overrides = published_card_overrides(db)
    article = catalog.by_slug(slug)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    published = public_payload(db, slug)
    markdown = (
        published["markdown"] if published is not None
        else (catalog.content_dir / "articles" / article.body_file).read_text(encoding="utf-8")
    )
    body, toc = (
        render_article(slug, published, public=True)
        if published is not None
        else render_article_body(catalog, article)
    )
    body = insert_inline_related(catalog, article, body)
    canonical = f"{BLOG_PUBLIC_ORIGIN}/articles/{article.slug}"
    social_image = article.card.file
    author = _author()
    breadcrumbs, breadcrumb_data = _breadcrumbs(article)
    dates = []
    article_dates = {}
    for label, key, value in (("Исходная публикация", "datePublished", article.original_published_at),
                               ("Обновлено в блоге", "dateModified", published.get("published_updated_at") if published else None)):
        if value:
            date = datetime.fromisoformat(value)
            dates.append(f'{label}: <time datetime="{escape(value, quote=True)}">{date:%d.%m.%Y}</time>')
            article_dates[key] = value
    hero_html = (
        f'<figure><img src="/blog/media/{escape(article.hero.file, quote=True)}" '
        f'alt="{escape(article.hero.alt, quote=True)}" loading="eager" '
        'decoding="async" fetchpriority="high"></figure>'
        if article.hero.show
        else ""
    )
    structured_data = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": article.title,
            "description": article.excerpt,
            "author": _person(author),
            **article_dates,
            "mainEntityOfPage": canonical,
            "image": f"{BLOG_PUBLIC_ORIGIN}/blog/media/{social_image}",
        },
        ensure_ascii=False,
    ).replace("</", r"<\/")
    replacements = {
        "{{TITLE}}": escape(article.title),
        "{{SEO_TITLE}}": escape(blog_seo_title(markdown, article.title)),
        "{{DESCRIPTION}}": escape(article.excerpt, quote=True),
        "{{CATEGORY}}": escape(article.category),
        "{{CANONICAL}}": escape(canonical, quote=True),
        "{{HERO_ABSOLUTE}}": escape(
            f"{BLOG_PUBLIC_ORIGIN}/blog/media/{social_image}", quote=True
        ),
        "{{HERO}}": hero_html,
        "{{BREADCRUMBS}}": breadcrumbs,
        "{{AUTHOR_BYLINE}}": f'<a class="author-byline" href="{escape(BLOG_PUBLIC_ORIGIN + author["path"], quote=True)}"><img src="{escape(author["image"], quote=True)}" alt="" width="32" height="32">{escape(author["name"])}, {escape(author["role"].lower())}</a>',
        "{{ARTICLE_DATES}}": '<div class="article-dates">' + ' · '.join(dates) + '</div>' if dates else '',
        "{{ARTICLE_BODY}}": body,
        "{{TOC_DESKTOP}}": toc_html(toc, mobile=False),
        "{{TOC_MOBILE}}": toc_html(toc, mobile=True),
        "{{READER_NAVIGATION}}": _template("reader-navigation.html").replace(
            "{{READER_TOC}}",
            ('<strong>В этом материале</strong><ol>' + ''.join(
                f'<li><a href="#{escape(anchor, quote=True)}">{escape(title)}</a></li>'
                for anchor, title in toc) + '</ol>') if len(toc) >= 3 else '',
        ),
        "{{RELATED_CARDS}}": related_cards_html(
            catalog, article, card_overrides=card_overrides
        ),
        "{{STRUCTURED_DATA}}": structured_data,
        "{{BREADCRUMB_DATA}}": json.dumps({"@context": "https://schema.org", **breadcrumb_data}, ensure_ascii=False).replace("</", r"<\/"),
    }
    rendered = re.sub(
        r"\{\{[A-Z_]+\}\}",
        lambda match: replacements.get(match.group(0), match.group(0)),
        _template("article.html"),
    )
    return _html_response(apply_responsive_images(rendered, catalog.content_dir, catalog.allowed_media))


@router.get("/blog/sitemap.xml", include_in_schema=False)
def blog_sitemap() -> Response:
    catalog = load_blog_catalog()
    locations = [BLOG_PUBLIC_ORIGIN, BLOG_PUBLIC_ORIGIN + _author()["path"], *(f"{BLOG_PUBLIC_ORIGIN}/articles/{article.slug}" for article in catalog.published)]
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
    if media_name not in catalog.allowed_media and media_name not in derivative_files(catalog.content_dir, catalog.allowed_media):
        raise HTTPException(status_code=404, detail="media not found")
    media_path = catalog.content_dir / "media" / media_name
    media_type = "image/webp" if media_path.suffix.lower() == ".webp" else mimetypes.guess_type(media_name)[0]
    response = FileResponse(media_path, media_type=media_type)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
