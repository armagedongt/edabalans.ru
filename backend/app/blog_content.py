"""Git-backed public blog catalogue, Markdown rendering and view helpers."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import re
import unicodedata

from fastapi import HTTPException

from app.article_markup import article_plain_text, markdown_to_article_html, safe_href
from app.public_cta_catalog import public_cta


BLOG_CATEGORIES = (
    "Похудение",
    "Пищевые привычки",
    "Калории",
    "Тренировки",
    "Качество питания",
    "Личное",
    "Ну, типа... ЗОЖ",
)
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class BlogHero:
    file: str
    alt: str
    provenance: str


@dataclass(frozen=True)
class BlogArticle:
    source_id: str
    slug: str
    title: str
    excerpt: str
    category: str
    body_file: str
    hero: BlogHero
    card: BlogHero
    related_source_ids: tuple[str, ...]
    cta: str
    status: str
    media: tuple[str, ...]


@dataclass(frozen=True)
class BlogCatalog:
    articles: tuple[BlogArticle, ...]
    content_dir: Path

    @property
    def published(self) -> tuple[BlogArticle, ...]:
        return tuple(article for article in self.articles if article.status == "published")

    def by_slug(self, slug: str) -> BlogArticle | None:
        return next((article for article in self.published if article.slug == slug), None)

    def by_source_id(self, source_id: str) -> BlogArticle | None:
        return next((article for article in self.published if article.source_id == source_id), None)

    @property
    def allowed_media(self) -> frozenset[str]:
        names: set[str] = set()
        for article in self.published:
            names.add(article.hero.file)
            names.add(article.card.file)
            names.update(article.media)
        return frozenset(names)


def default_content_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "content" / "blog"


def _required_text(raw: dict, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"blog article field {key} must be a non-empty string")
    return value.strip()


def load_blog_catalog(content_dir: Path | None = None) -> BlogCatalog:
    root = (content_dir or default_content_dir()).resolve()
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("articles"), list):
        raise ValueError("blog manifest version 1 with articles list is required")

    articles: list[BlogArticle] = []
    for raw in payload["articles"]:
        if not isinstance(raw, dict):
            raise ValueError("blog article entry must be an object")
        source_id = _required_text(raw, "source_id")
        slug = _required_text(raw, "slug")
        title = _required_text(raw, "title")
        excerpt = _required_text(raw, "excerpt")
        category = _required_text(raw, "category")
        body_file = _required_text(raw, "body_file")
        cta = _required_text(raw, "cta")
        status = _required_text(raw, "status")
        hero_raw = raw.get("hero")
        if not isinstance(hero_raw, dict):
            raise ValueError(f"blog article {source_id} must have hero metadata")
        hero = BlogHero(
            file=_required_text(hero_raw, "file"),
            alt=_required_text(hero_raw, "alt"),
            provenance=_required_text(hero_raw, "provenance"),
        )
        card_raw = raw.get("card")
        if not isinstance(card_raw, dict):
            raise ValueError(f"blog article {source_id} must have card metadata")
        card = BlogHero(
            file=_required_text(card_raw, "file"),
            alt=_required_text(card_raw, "alt"),
            provenance=_required_text(card_raw, "provenance"),
        )
        related_raw = raw.get("related_source_ids")
        media_raw = raw.get("media", [])
        if not isinstance(related_raw, list) or not all(isinstance(item, str) for item in related_raw):
            raise ValueError(f"blog article {source_id} related_source_ids must be a string list")
        if not isinstance(media_raw, list) or not all(isinstance(item, str) for item in media_raw):
            raise ValueError(f"blog article {source_id} media must be a string list")
        article = BlogArticle(
            source_id=source_id,
            slug=slug,
            title=title,
            excerpt=excerpt,
            category=category,
            body_file=body_file,
            hero=hero,
            card=card,
            related_source_ids=tuple(related_raw),
            cta=cta,
            status=status,
            media=tuple(media_raw),
        )
        articles.append(article)

    catalog = BlogCatalog(tuple(articles), root)
    validate_blog_catalog(catalog)
    return catalog


def _safe_relative_file(value: str) -> bool:
    candidate = Path(value)
    return bool(value) and not candidate.is_absolute() and ".." not in candidate.parts and "\\" not in value


def validate_blog_catalog(catalog: BlogCatalog) -> None:
    source_ids = [article.source_id for article in catalog.articles]
    slugs = [article.slug for article in catalog.articles]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("blog source_id values must be unique")
    if len(slugs) != len(set(slugs)):
        raise ValueError("blog slugs must be unique")
    published_ids = {article.source_id for article in catalog.published}

    for article in catalog.articles:
        if not SLUG_RE.fullmatch(article.slug):
            raise ValueError(f"invalid blog slug: {article.slug}")
        if article.category not in BLOG_CATEGORIES:
            raise ValueError(f"unknown blog category: {article.category}")
        if article.status not in {"draft", "published"}:
            raise ValueError(f"unknown blog status: {article.status}")
        if public_cta(article.cta) is None:
            raise ValueError(f"unknown public CTA: {article.cta}")
        if not _safe_relative_file(article.body_file) or not (catalog.content_dir / "articles" / article.body_file).is_file():
            raise ValueError(f"missing blog body: {article.body_file}")
        body = (catalog.content_dir / "articles" / article.body_file).read_text(encoding="utf-8")
        declared_media = (article.hero.file, article.card.file, *article.media)
        for media_file in declared_media:
            if not _safe_relative_file(media_file) or not (catalog.content_dir / "media" / media_file).is_file():
                raise ValueError(f"missing blog media: {media_file}")
        if article.status == "published":
            if "placeholder" in body.casefold() or "temporary development" in body.casefold():
                raise ValueError(f"published blog article {article.source_id} contains placeholder copy")
            if re.search(r"!\[[^\]]*\]\(https?://", body):
                raise ValueError(f"published blog article {article.source_id} hotlinks an external image")
            if re.search(r"<\s*/?\s*[A-Za-z][^>]*>", body):
                raise ValueError(f"published blog article {article.source_id} contains forbidden HTML")
            component_count = 0
            def validate_component(name: str, arguments: list[str]) -> str:
                nonlocal component_count
                if name != "blog_cta" or arguments != [article.cta]:
                    raise HTTPException(422, "Article component does not match its manifest CTA")
                component_count += 1
                return render_blog_component(name, arguments)

            try:
                markdown_to_article_html(body, component_renderer=validate_component)
            except HTTPException as exc:
                raise ValueError(
                    f"published blog article {article.source_id} has an invalid directive: {exc.detail}"
                ) from exc
            if component_count != 1:
                raise ValueError(
                    f"published blog article {article.source_id} must contain exactly one CTA directive"
                )
            referenced_media = set(re.findall(r"!\[[^\]]*\]\(/blog/media/([^)]+)\)", body))
            undeclared_media = referenced_media - set(declared_media)
            if undeclared_media:
                raise ValueError(
                    f"published blog article {article.source_id} uses undeclared media: {sorted(undeclared_media)}"
                )
            if len(article.related_source_ids) != 3 or len(set(article.related_source_ids)) != 3:
                raise ValueError(f"published blog article {article.source_id} must have three unique related items")
            if article.source_id in article.related_source_ids:
                raise ValueError(f"blog article {article.source_id} cannot relate to itself")
            unknown = set(article.related_source_ids) - published_ids
            if unknown:
                raise ValueError(f"blog article {article.source_id} links unpublished or unknown related items: {sorted(unknown)}")


def render_blog_component(name: str, arguments: list[str]) -> str:
    if name != "blog_cta" or len(arguments) != 1:
        raise HTTPException(422, "Компонент блога принимает один ключ CTA")
    cta = public_cta(arguments[0])
    if cta is None or not safe_href(cta.destination):
        raise HTTPException(422, "Неизвестный или небезопасный CTA блога")
    return (
        f'<section class="blog-cta blog-cta-{escape(cta.key)}" data-component="blog-cta">'
        f'<span class="blog-cta-eyebrow">{escape(cta.eyebrow)}</span>'
        f'<h3>{escape(cta.title)}</h3><p>{escape(cta.copy)}</p>'
        f'<a href="{escape(cta.destination, quote=True)}" data-tracking-key="{escape(cta.tracking_key, quote=True)}">'
        f'{escape(cta.button_label)}</a></section>'
    )


def _heading_anchor(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("_", "-")
    slug = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE).strip("-")
    return slug or "section"


def add_heading_anchors(rendered: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    used: dict[str, int] = {}
    toc: list[tuple[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        level, body = match.groups()
        title = " ".join(article_plain_text(body).split())
        base = _heading_anchor(title)
        used[base] = used.get(base, 0) + 1
        anchor = base if used[base] == 1 else f"{base}-{used[base]}"
        if level == "2":
            toc.append((anchor, title))
        return f'<h{level} id="{escape(anchor, quote=True)}">{body}</h{level}>'

    with_anchors = re.sub(r"<h([23])>(.*?)</h\1>", replace, rendered, flags=re.DOTALL)
    return with_anchors, tuple(toc)


def render_article_body(catalog: BlogCatalog, article: BlogArticle) -> tuple[str, tuple[tuple[str, str], ...]]:
    source = (catalog.content_dir / "articles" / article.body_file).read_text(encoding="utf-8")
    rendered = markdown_to_article_html(source, component_renderer=render_blog_component)
    return add_heading_anchors(rendered)


def card_html(article: BlogArticle, *, heading_level: int = 2) -> str:
    if heading_level not in {2, 3}:
        raise ValueError("blog card heading level must be 2 or 3")
    return (
        f'<article class="article-card" data-category="{escape(article.category, quote=True)}">'
        f'<a class="card-link" href="/articles/{escape(article.slug, quote=True)}">'
        '<div class="card-visual">'
        f'<img src="/blog/media/{escape(article.card.file, quote=True)}" '
        f'alt="{escape(article.card.alt, quote=True)}" loading="lazy"></div>'
        f'<div class="card-body"><span class="card-tag">{escape(article.category)}</span>'
        f'<h{heading_level} class="card-title">{escape(article.title)}</h{heading_level}>'
        f'<p class="card-copy">{escape(article.excerpt)}</p></div></a></article>'
    )


def related_cards_html(catalog: BlogCatalog, article: BlogArticle) -> str:
    related = [catalog.by_source_id(source_id) for source_id in article.related_source_ids]
    if any(item is None for item in related):
        raise ValueError(f"blog article {article.source_id} has unresolved related items")
    return "".join(card_html(item, heading_level=3) for item in related if item is not None)


def toc_html(toc: tuple[tuple[str, str], ...], *, mobile: bool) -> str:
    if len(toc) < 3:
        return ""
    items = "".join(f'<li><a href="#{escape(anchor, quote=True)}">{escape(title)}</a></li>' for anchor, title in toc)
    if mobile:
        return (
            '<details class="toc-mobile"><summary>Содержание</summary>'
            f'<nav aria-label="Содержание"><strong>В этом материале</strong><ol>{items}</ol></nav></details>'
        )
    return (
        '<aside class="toc-dock"><button class="toc-button" type="button" aria-expanded="false" '
        'aria-controls="article-toc">Содержание</button>'
        f'<nav class="toc-popover" id="article-toc" aria-label="Содержание" hidden>'
        f'<strong>В этом материале</strong><ol>{items}</ol></nav></aside>'
    )
