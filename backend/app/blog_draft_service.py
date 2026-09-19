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
    render_blog_component,
)
from app.managed_documents import (
    active_document,
    document_hash,
    publish_document,
    version_history,
)
from app.models import ManagedDocumentVersion
from app.public_cta_catalog import public_cta


DOCUMENT_TYPE = "blog-article-draft"
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


def _invalid(detail: str) -> HTTPException:
    return HTTPException(422, detail)


def _valid_source(value: str) -> bool:
    if value.startswith("content://"):
        return bool(value.removeprefix("content://").strip())
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _validate_markdown(markdown: str, media_names: set[str]) -> str:
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
    allowed = {f"/media/{name}" for name in media_names}
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
    markdown = str(source.get("markdown") or "")
    markdown_sha256 = _validate_markdown(markdown, seen)
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
        "media": media,
        "metadata": deepcopy(metadata),
    }


def active_article(db: Session, slug: str) -> ManagedDocumentVersion:
    article = active_document(db, DOCUMENT_TYPE, slug)
    if article is None:
        raise HTTPException(404, "Материал не найден")
    return article


def save_package(
    db: Session, *, slug: str, source: dict, expected_version: int, admin: str
) -> ManagedDocumentVersion:
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
    db: Session, *, slug: str, markdown: str, expected_version: int, admin: str
) -> ManagedDocumentVersion:
    current = active_article(db, slug)
    payload = deepcopy(current.payload)
    payload["markdown_sha256"] = _validate_markdown(
        markdown, {item["name"] for item in payload["media"]}
    )
    payload["markdown"] = markdown
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
    return list(
        db.scalars(
            select(ManagedDocumentVersion)
            .where(
                ManagedDocumentVersion.document_type == DOCUMENT_TYPE,
                ManagedDocumentVersion.is_active.is_(True),
            )
            .order_by(ManagedDocumentVersion.created_at.desc())
        )
    )


def serialize_article(version: ManagedDocumentVersion, *, source: bool) -> dict:
    payload = version.payload
    media = [
        {
            **{key: item[key] for key in ("name", "sha256", "mime", "provenance", "alt", "width", "height")},
            "url": f"/blog/drafts/{version.document_key}/media/{item['name']}",
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
        "metadata": payload["metadata"],
        "markdown_sha256": payload["markdown_sha256"],
        "media": media,
        "updated_at": version.created_at.isoformat(),
        "updated_by": version.created_by,
    }
    if source:
        result["markdown"] = payload["markdown"]
    return result


def media_bytes(version: ManagedDocumentVersion, name: str) -> tuple[bytes, str, str]:
    item = next((value for value in version.payload["media"] if value["name"] == name), None)
    if item is None:
        raise HTTPException(404, "Изображение не найдено")
    raw = base64.b64decode(item["content_base64"], validate=True)
    if hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise HTTPException(503, "Нарушена целостность изображения")
    return raw, item["mime"], item["sha256"]


def render_article(slug: str, payload: dict, markdown: str | None = None) -> tuple[str, tuple]:
    value = payload["markdown"] if markdown is None else markdown
    _validate_markdown(value, {item["name"] for item in payload["media"]})
    for item in payload["media"]:
        value = re.sub(
            r"(?<=\]\()" + re.escape(f"/media/{item['name']}") + r"(?=[\s)])",
            f"/blog/drafts/{slug}/media/{item['name']}",
            value,
        )
    body = markdown_to_article_html(value)
    body += render_blog_component("blog_cta", [payload["cta"]])
    return add_heading_anchors(body)
