"""Versioned, admin-only Markdown packages for the blog authoring test slice."""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from io import BytesIO
import hashlib
import json
import re
from urllib.parse import urlsplit
import warnings

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.article_markup import markdown_to_article_html
from app.blog_content import (
    BLOG_CATEGORIES,
    SLUG_RE,
    add_heading_anchors,
    default_content_dir,
    load_blog_catalog,
    render_blog_component,
)
from app.managed_documents import (
    active_document,
    document_hash,
    ensure_seed_document,
    publish_document,
    version_history,
)
from app.models import ManagedDocumentVersion
from app.public_cta_catalog import public_cta


DOCUMENT_TYPE = "blog-article-draft"
PUBLISHED_DOCUMENT_TYPE = "blog-article-published"
SCHEMA_VERSION = 1
MAX_MARKDOWN_BYTES = 250 * 1024
MAX_MEDIA_COUNT = 8
MAX_MEDIA_BYTES = 1024 * 1024
MAX_TOTAL_MEDIA_BYTES = 4 * 1024 * 1024
MAX_METADATA_BYTES = 100 * 1024
MAX_IMAGE_EDGE = 6000
MAX_IMAGE_PIXELS = 25_000_000
MEDIA_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,91}\.(?:png|jpg|webp)")
MEDIA_MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
PIL_FORMAT = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP"}
CARD_FITS = {"cover", "contain"}
BLOG_CTA_RE = re.compile(
    r"\n*blog_cta\(\s*\n\s*[a-z0-9_-]+\s*\n\)",
    re.MULTILINE,
)


def _invalid(detail: str) -> HTTPException:
    return HTTPException(422, detail)


def _valid_source(value: str) -> bool:
    if value.startswith("content://"):
        return bool(value.removeprefix("content://").strip())
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _media_source(item: dict) -> str:
    if item.get("storage") == "git":
        return f"/blog/media/{item['name']}"
    return f"/media/{item['name']}"


def _validate_card(card: str | None, card_fit: str, media: list[dict]) -> tuple[str | None, str]:
    if card is not None and card not in {item["name"] for item in media}:
        raise _invalid("Обложка должна ссылаться на изображение этой статьи")
    if card_fit not in CARD_FITS:
        raise _invalid("Режим обложки должен быть cover или contain")
    return card, card_fit


def _validate_markdown(markdown: str, media: list[dict]) -> str:
    if not markdown.strip():
        raise _invalid("Markdown статьи не может быть пустым")
    if len(markdown.encode("utf-8")) > MAX_MARKDOWN_BYTES:
        raise _invalid("Markdown статьи превышает 250 KiB")
    if re.search(r"(?m)^\s*#\s+", markdown) or re.search(
        r"(?m)^\s{0,3}\S[^\n]*\n\s{0,3}=+\s*$", markdown
    ):
        raise _invalid("H1 хранится в metadata, а не в теле статьи")
    if "<!--" in markdown or "-->" in markdown or re.search(
        r"<\s*/?\s*[A-Za-z][^>]*>", markdown
    ):
        raise _invalid("Raw HTML и HTML-комментарии в статье запрещены")
    if re.search(r"(?m)^\s*[a-z][\w-]*\(\s*$", markdown):
        raise _invalid("Компоненты и CTA не хранятся в Markdown статьи")

    image_sources = re.findall(r"!\[[^\]]*\]\(([^\s)]+)", markdown)
    allowed = {_media_source(item) for item in media}
    if any(source not in allowed for source in image_sources):
        raise _invalid("Изображение должно ссылаться на media из того же пакета")
    markdown_to_article_html(markdown)
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _decode_media(item: dict) -> tuple[dict, int]:
    name = str(item.get("name") or "")
    if not MEDIA_NAME_RE.fullmatch(name):
        raise _invalid("Недопустимое имя изображения")
    provenance = str(item.get("provenance") or "").strip()
    if not provenance or len(provenance) > 2000:
        raise _invalid("Для изображения нужен provenance до 2000 символов")
    alt = str(item.get("alt") or "")
    if len(alt) > 500:
        raise _invalid("Alt изображения превышает 500 символов")
    encoded = str(item.get("content_base64") or "")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _invalid("Изображение закодировано неверно") from exc
    if not raw or len(raw) > MAX_MEDIA_BYTES:
        raise _invalid("Изображение должно занимать от 1 байта до 1 MiB")

    extension = name.rsplit(".", 1)[1]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=[PIL_FORMAT[extension]]) as image:
                width, height = image.size
                if (
                    width < 1
                    or height < 1
                    or width > MAX_IMAGE_EDGE
                    or height > MAX_IMAGE_EDGE
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise _invalid("Размер изображения превышает 6000 px или 25 млн пикселей")
                if image.format != PIL_FORMAT[extension]:
                    raise _invalid("Расширение изображения не совпадает с форматом")
                image.verify()
            with Image.open(BytesIO(raw), formats=[PIL_FORMAT[extension]]) as image:
                image.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise _invalid("Файл не является допустимым PNG, JPEG или WebP") from exc
    except Image.DecompressionBombWarning as exc:
        raise _invalid("Изображение содержит слишком много пикселей") from exc

    return (
        {
            "name": name,
            "content_base64": base64.b64encode(raw).decode("ascii"),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "mime": MEDIA_MIME[extension],
            "provenance": provenance,
            "alt": alt,
            "width": width,
            "height": height,
        },
        len(raw),
    )


def prepare_package(slug: str, source: dict) -> dict:
    if not SLUG_RE.fullmatch(slug):
        raise _invalid("Slug содержит недопустимые символы")
    title = str(source.get("title") or "").strip()
    excerpt = str(source.get("excerpt") or "").strip()
    category = str(source.get("category") or "")
    visibility = str(source.get("visibility") or "public")
    cta = str(source.get("cta") or "")
    sources = source.get("sources")
    metadata = source.get("metadata") or {}
    media_source = source.get("media") or []
    if not title or len(title) > 200:
        raise _invalid("Название должно содержать от 1 до 200 символов")
    if len(excerpt) > 500:
        raise _invalid("Excerpt превышает 500 символов")
    if category not in BLOG_CATEGORIES:
        raise _invalid("Неизвестная рубрика блога")
    if visibility not in {"public", "internal"}:
        raise _invalid("visibility должен быть public или internal")
    if source.get("editorial_status", "moderation") != "moderation":
        raise _invalid("Новые DB-материалы сохраняются только на модерации")
    if public_cta(cta) is None:
        raise _invalid("Неизвестная конечная плашка")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 20:
        raise _invalid("Нужен список из 1–20 источников")
    normalized_sources = [str(value).strip() for value in sources]
    if any(not _valid_source(value) for value in normalized_sources):
        raise _invalid("Источник должен быть http(s) URL или content:// ID")
    if not isinstance(metadata, dict):
        raise _invalid("metadata должна быть JSON-объектом")
    if len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) > MAX_METADATA_BYTES:
        raise _invalid("metadata превышает 100 KiB")
    if not isinstance(media_source, list) or len(media_source) > MAX_MEDIA_COUNT:
        raise _invalid("В пакете допускается не больше восьми изображений")

    media: list[dict] = []
    total = 0
    seen: set[str] = set()
    for item in media_source:
        if not isinstance(item, dict):
            raise _invalid("Описание изображения должно быть объектом")
        prepared, size = _decode_media(item)
        if prepared["name"] in seen:
            raise _invalid("Имена изображений в пакете не должны повторяться")
        seen.add(prepared["name"])
        total += size
        media.append(prepared)
    if total > MAX_TOTAL_MEDIA_BYTES:
        raise _invalid("Изображения пакета суммарно превышают 4 MiB")

    hero = source.get("hero")
    if hero is not None and hero not in seen:
        raise _invalid("Hero должен ссылаться на изображение из пакета")
    manifest_article = load_blog_catalog().by_slug(slug)
    manifest_card = manifest_article.card.file if manifest_article is not None else None
    requested_card = source.get("card")
    selected_card = requested_card or (manifest_card if manifest_card in seen else hero)
    selected_fit = source.get("card_fit")
    if selected_fit is None:
        selected_fit = (
            manifest_article.card.fit
            if manifest_article is not None and selected_card == manifest_card
            else "cover"
        )
    card, card_fit = _validate_card(
        selected_card,
        str(selected_fit),
        media,
    )
    markdown = str(source.get("markdown") or "")
    markdown_sha256 = _validate_markdown(markdown, media)
    source_id = source.get("source_id")
    if source_id is not None and (not str(source_id).strip() or len(str(source_id)) > 160):
        raise _invalid("source_id превышает 160 символов")

    return {
        "title": title,
        "excerpt": excerpt,
        "category": category,
        "markdown": markdown,
        "markdown_sha256": markdown_sha256,
        "visibility": visibility,
        "editorial_status": "moderation",
        "cta": cta,
        "sources": normalized_sources,
        "source_id": str(source_id).strip() if source_id is not None else None,
        "hero": hero,
        "card": card,
        "card_fit": card_fit,
        "media": media,
        "metadata": deepcopy(metadata),
    }


def _existing_catalog_article(slug: str):
    catalog = load_blog_catalog()
    article = catalog.by_slug(slug)
    if article is None:
        raise HTTPException(404, "Материал не найден")
    return catalog, article


def _git_seed_payload(slug: str) -> dict:
    catalog, article = _existing_catalog_article(slug)
    markdown = (catalog.content_dir / "articles" / article.body_file).read_text(encoding="utf-8")
    markdown, cta_count = BLOG_CTA_RE.subn("", markdown)
    if cta_count != 1:
        raise ValueError(f"blog article {article.source_id} must contain exactly one CTA directive")
    markdown = markdown.rstrip() + "\n"
    names = tuple(dict.fromkeys((article.hero.file, article.card.file, *article.media)))
    media = []
    for name in names:
        path = catalog.content_dir / "media" / name
        raw = path.read_bytes()
        mime = "image/webp" if path.suffix.casefold() == ".webp" else (
            "image/gif" if path.suffix.casefold() == ".gif" else f"image/{path.suffix.lstrip('.').casefold().replace('jpg', 'jpeg')}"
        )
        width = height = 0
        try:
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
        except (UnidentifiedImageError, OSError):
            pass
        media.append({
            "name": name,
            "storage": "git",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "mime": mime,
            "provenance": (
                article.hero.provenance if name == article.hero.file else
                article.card.provenance if name == article.card.file else
                f"content://blog/media/{name}"
            ),
            "alt": (
                article.hero.alt if name == article.hero.file else
                article.card.alt if name == article.card.file else ""
            ),
            "width": width,
            "height": height,
        })
    return {
        "title": article.title,
        "excerpt": article.excerpt,
        "category": article.category,
        "markdown": markdown,
        "markdown_sha256": _validate_markdown(markdown, media),
        "visibility": "public",
        "editorial_status": "moderation",
        "cta": article.cta,
        "sources": [f"content://blog/{article.source_id}"],
        "source_id": article.source_id,
        "hero": article.hero.file if article.hero.show else None,
        "card": article.card.file,
        "card_fit": article.card.fit,
        "media": media,
        "metadata": {
            "body_file": article.body_file,
            "related_source_ids": list(article.related_source_ids),
            "seed_source": "content/blog/manifest.json",
        },
    }


def ensure_existing_article(db: Session, slug: str) -> ManagedDocumentVersion:
    _existing_catalog_article(slug)
    return ensure_seed_document(
        db,
        document_type=DOCUMENT_TYPE,
        document_key=slug,
        schema_version=SCHEMA_VERSION,
        payload=_git_seed_payload(slug),
    )


def _published_article(db: Session, slug: str) -> ManagedDocumentVersion | None:
    return active_document(db, PUBLISHED_DOCUMENT_TYPE, slug)


def _matches_manifest_contract(payload: dict, seed: dict) -> bool:
    controlled = (
        "title",
        "excerpt",
        "category",
        "visibility",
        "cta",
        "source_id",
        "hero",
    )
    if any(payload.get(key) != seed.get(key) for key in controlled):
        return False
    payload_media = [
        (item.get("name"), item.get("storage"))
        for item in payload.get("media", [])
    ]
    seed_media = [(item["name"], item.get("storage")) for item in seed["media"]]
    return payload_media == seed_media


def _manifest_managed(payload: dict) -> bool:
    return payload.get("metadata", {}).get("seed_source") == "content/blog/manifest.json"


def effective_article_payload(version: ManagedDocumentVersion) -> dict:
    """Refresh manifest-owned fields without discarding a saved body revision."""
    if not _manifest_managed(version.payload):
        return version.payload
    seed = _git_seed_payload(version.document_key)
    if version.version_no == 1 and version.created_by == "system-seed":
        return seed
    seed["markdown"] = version.payload["markdown"]
    seed["markdown_sha256"] = version.payload["markdown_sha256"]
    seed["visibility"] = version.payload.get("visibility", "public")
    allowed_cards = {item["name"] for item in seed["media"]}
    selected_card = version.payload.get("card", seed["card"])
    selected_fit = version.payload.get("card_fit", seed["card_fit"])
    if selected_card not in allowed_cards:
        selected_card, selected_fit = seed["card"], seed["card_fit"]
    seed["card"], seed["card_fit"] = _validate_card(
        selected_card, selected_fit, seed["media"]
    )
    return seed


def publication_status(db: Session, version: ManagedDocumentVersion) -> tuple[str, int | None]:
    published = _published_article(db, version.document_key)
    if published is not None:
        payload = effective_article_payload(version)
        defaults = _git_seed_payload(version.document_key)
        allowed_cards = {item["name"] for item in defaults["media"]}
        published_card = published.payload.get("card", defaults["card"])
        published_fit = published.payload.get("card_fit", defaults["card_fit"])
        if published_card not in allowed_cards:
            published_card, published_fit = defaults["card"], defaults["card_fit"]
        return (
            "published"
            if (
                published.payload.get("markdown_sha256")
                == payload.get("markdown_sha256")
                and published_card == payload.get("card")
                and published_fit == payload.get("card_fit")
            )
            else "moderation",
            published.version_no,
        )
    return (
        "published"
        if version.version_no == 1 and version.created_by == "system-seed"
        else "moderation",
        0,
    )


def active_article(db: Session, slug: str) -> ManagedDocumentVersion:
    article = active_document(db, DOCUMENT_TYPE, slug)
    if article is None:
        article = ensure_existing_article(db, slug)
    else:
        _existing_catalog_article(slug)
    return article


def save_package(
    db: Session, *, slug: str, source: dict, expected_version: int, admin: str
) -> ManagedDocumentVersion:
    _existing_catalog_article(slug)
    payload = prepare_package(slug, source)
    current = active_document(db, DOCUMENT_TYPE, slug)
    if current is None:
        if expected_version != 0:
            raise HTTPException(409, "Материал уже изменён или ещё не создан")
        version = ManagedDocumentVersion(
            document_type=DOCUMENT_TYPE,
            document_key=slug,
            schema_version=SCHEMA_VERSION,
            version_no=1,
            payload=payload,
            content_hash=document_hash(payload),
            created_by=admin,
            is_active=True,
        )
        db.add(version)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Материал уже создан в другой вкладке") from exc
        db.refresh(version)
        return version
    return publish_document(
        db,
        document_type=DOCUMENT_TYPE,
        document_key=slug,
        schema_version=SCHEMA_VERSION,
        payload=payload,
        expected_version=expected_version,
        admin=admin,
    )


def update_text(
    db: Session,
    *,
    slug: str,
    markdown: str,
    card: str | None = None,
    card_fit: str | None = None,
    expected_version: int,
    admin: str,
) -> ManagedDocumentVersion:
    current = active_article(db, slug)
    payload = deepcopy(effective_article_payload(current))
    payload["markdown_sha256"] = _validate_markdown(markdown, payload["media"])
    payload["markdown"] = markdown
    if card is not None or card_fit is not None:
        payload["card"], payload["card_fit"] = _validate_card(
            card if card is not None else payload.get("card"),
            card_fit if card_fit is not None else payload.get("card_fit", "cover"),
            payload["media"],
        )
    payload["editorial_status"] = "moderation"
    return publish_document(
        db,
        document_type=DOCUMENT_TYPE,
        document_key=slug,
        schema_version=SCHEMA_VERSION,
        payload=payload,
        expected_version=expected_version,
        admin=admin,
    )


def article_versions(db: Session, slug: str) -> list[ManagedDocumentVersion]:
    return version_history(db, DOCUMENT_TYPE, slug)


def active_articles(db: Session) -> list[ManagedDocumentVersion]:
    catalog = load_blog_catalog()
    for article in catalog.published:
        ensure_existing_article(db, article.slug)
    allowed = [article.slug for article in catalog.published]
    return list(
        db.scalars(
            select(ManagedDocumentVersion)
            .where(
                ManagedDocumentVersion.document_type == DOCUMENT_TYPE,
                ManagedDocumentVersion.is_active.is_(True),
                ManagedDocumentVersion.document_key.in_(allowed),
            )
            .order_by(ManagedDocumentVersion.created_at.desc())
        )
    )


def serialize_article(version: ManagedDocumentVersion, *, source: bool, db: Session | None = None) -> dict:
    payload = effective_article_payload(version)
    media = [
        {
            **{key: item[key] for key in ("name", "sha256", "mime", "provenance", "alt", "width", "height")},
            "url": (
                f"/blog/media/{item['name']}" if item.get("storage") == "git" else
                f"/blog/drafts/{version.document_key}/media/{item['name']}"
            ),
        }
        for item in payload["media"]
    ]
    result = {
        "slug": version.document_key,
        "version": version.version_no,
        "title": payload["title"],
        "excerpt": payload["excerpt"],
        "category": payload["category"],
        "visibility": payload["visibility"],
        "editorial_status": payload["editorial_status"],
        "cta": payload["cta"],
        "source_id": payload.get("source_id"),
        "sources": payload["sources"],
        "hero": payload.get("hero"),
        "card": payload.get("card"),
        "card_fit": payload.get("card_fit", "cover"),
        "metadata": payload["metadata"],
        "markdown_sha256": payload["markdown_sha256"],
        "media": media,
        "updated_at": version.created_at.isoformat(),
        "updated_by": version.created_by,
    }
    if db is not None:
        status, published_version = publication_status(db, version)
        result["editorial_status"] = status
        result["published_version"] = published_version
    if source:
        result["markdown"] = payload["markdown"]
    return result


def media_bytes(version: ManagedDocumentVersion, name: str) -> tuple[bytes, str, str]:
    payload = effective_article_payload(version)
    item = next((value for value in payload["media"] if value["name"] == name), None)
    if item is None:
        raise HTTPException(404, "Изображение не найдено")
    if item.get("storage") == "git":
        raw = (default_content_dir() / "media" / item["name"]).read_bytes()
    else:
        raw = base64.b64decode(item["content_base64"], validate=True)
    if hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise HTTPException(503, "Нарушена целостность изображения")
    return raw, item["mime"], item["sha256"]


def render_article(
    slug: str,
    payload: dict,
    markdown: str | None = None,
    *,
    public: bool = False,
) -> tuple[str, tuple]:
    value = payload["markdown"] if markdown is None else markdown
    _validate_markdown(value, payload["media"])
    for item in payload["media"]:
        if item.get("storage") == "git":
            continue
        value = re.sub(
            r"(?<=\]\()" + re.escape(f"/media/{item['name']}") + r"(?=[\s)])",
            (
                f"/articles/{slug}/media/{item['name']}"
                if public
                else f"/blog/drafts/{slug}/media/{item['name']}"
            ),
            value,
        )
    body = markdown_to_article_html(value)
    body += render_blog_component("blog_cta", [payload["cta"]])
    return add_heading_anchors(body)


def publish_article(
    db: Session, *, slug: str, expected_version: int, admin: str
) -> ManagedDocumentVersion:
    draft = active_article(db, slug)
    if draft.version_no != expected_version:
        raise HTTPException(409, "Материал уже изменён в другой вкладке")
    draft_payload = effective_article_payload(draft)
    if draft_payload.get("visibility") != "public":
        raise _invalid("Служебный материал нельзя опубликовать")
    public_payload = _git_seed_payload(slug)
    if not _manifest_managed(draft.payload) and not _matches_manifest_contract(
        draft.payload, public_payload
    ):
        raise _invalid(
            "На текущем этапе публично меняется только Markdown; metadata и media берутся из manifest"
        )
    public_payload["markdown"] = draft_payload["markdown"]
    public_payload["markdown_sha256"] = _validate_markdown(
        draft_payload["markdown"], public_payload["media"]
    )
    public_payload["card"], public_payload["card_fit"] = _validate_card(
        draft_payload.get("card"),
        draft_payload.get("card_fit", "cover"),
        public_payload["media"],
    )
    current = _published_article(db, slug)
    if current is None:
        version = ManagedDocumentVersion(
            document_type=PUBLISHED_DOCUMENT_TYPE,
            document_key=slug,
            schema_version=SCHEMA_VERSION,
            version_no=1,
            payload=public_payload,
            content_hash=document_hash(public_payload),
            created_by=admin,
            is_active=True,
        )
        db.add(version)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Публикация уже изменилась в другой вкладке") from exc
        db.refresh(version)
        return version
    return publish_document(
        db,
        document_type=PUBLISHED_DOCUMENT_TYPE,
        document_key=slug,
        schema_version=SCHEMA_VERSION,
        payload=public_payload,
        expected_version=current.version_no,
        admin=admin,
    )


def public_payload(db: Session, slug: str) -> dict | None:
    """Overlay the published body on the current manifest-owned contract."""
    published = _published_article(db, slug)
    if published is None:
        _existing_catalog_article(slug)
        return None
    payload = _git_seed_payload(slug)
    payload["markdown"] = published.payload["markdown"]
    payload["markdown_sha256"] = published.payload["markdown_sha256"]
    allowed_cards = {item["name"] for item in payload["media"]}
    selected_card = published.payload.get("card", payload["card"])
    selected_fit = published.payload.get("card_fit", payload["card_fit"])
    if selected_card not in allowed_cards:
        selected_card, selected_fit = payload["card"], payload["card_fit"]
    payload["card"], payload["card_fit"] = _validate_card(
        selected_card,
        selected_fit,
        payload["media"],
    )
    return payload


def published_card_overrides(db: Session) -> dict[str, tuple[str, str]]:
    catalog = load_blog_catalog()
    articles = {article.slug: article for article in catalog.published}
    rows = db.scalars(
        select(ManagedDocumentVersion).where(
            ManagedDocumentVersion.document_type == PUBLISHED_DOCUMENT_TYPE,
            ManagedDocumentVersion.is_active.is_(True),
            ManagedDocumentVersion.document_key.in_(articles),
        )
    )
    result: dict[str, tuple[str, str]] = {}
    for row in rows:
        article = articles.get(row.document_key)
        if article is None:
            continue
        allowed = {article.hero.file, article.card.file, *article.media}
        card = row.payload.get("card")
        fit = row.payload.get("card_fit", "cover")
        if card in allowed and fit in CARD_FITS:
            result[row.document_key] = (card, fit)
    return result
