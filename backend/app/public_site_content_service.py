from __future__ import annotations

from app.site_links import relative_site_html

from copy import deepcopy
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.article_markup import inline_markdown, markdown_to_article_html, safe_href
from app.managed_documents import active_document, ensure_seed_document, publish_document
from app.models import ManagedDocumentVersion


DOCUMENT_TYPE = "public-site-content"
SCHEMA_VERSION = 1
VERSION_MARKER = re.compile(r"\A<!-- public-site-version: [0-9]+ -->\s*")
CONTENT_ROOT = Path(__file__).resolve().parents[2] / "content" / "public-site" / "homepage"

DOCUMENTS = {
    "approach": {"title": "Как устроен подход", "kind": "article", "file": "approach.md"},
    "program": {"title": "Основная программа", "kind": "article", "file": "program.md"},
    "recipes": {"title": "Система рецептов", "kind": "article", "file": "recipes.md"},
    "consultation": {"title": "Индивидуальная консультация", "kind": "article", "file": "consultation.md"},
    "calories": {"title": "Мини-курс «Калорийный»", "kind": "article", "file": "calories.md"},
    "training": {"title": "Мини-курс «С мягкого дивана до регулярных тренировок»", "kind": "article", "file": "training.md"},
    "faq": {"title": "Частые вопросы", "kind": "faq", "file": "faq.md"},
    "reader-subscription": {
        "title": "Блок статьи и подписки", "kind": "reader-subscription", "file": "reader-subscription.md",
    },
}


class ReaderSubscriptionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    telegram_url: str = Field(min_length=1, max_length=2048)
    max_url: str = Field(min_length=1, max_length=2048)


def render_reader_subscription_source(markdown: str) -> dict:
    source = VERSION_MARKER.sub("", markdown, count=1).lstrip()
    match = re.fullmatch(r"```json\n(.*?)\n```\s*\n(.+)", source, re.S)
    if match is None:
        raise HTTPException(422, "Сохраните JSON-настройки блока перед текстом")
    try:
        settings = ReaderSubscriptionSettings.model_validate(json.loads(match[1])).model_dump()
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, "Проверьте ссылки блока") from exc
    for key, host in (("telegram_url", "t.me"), ("max_url", "max.ru")):
        value = settings[key]
        try:
            parsed = urlsplit(value)
            valid = safe_href(value) and parsed.scheme == "https" and parsed.netloc == host and bool(parsed.path.strip("/"))
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(422, f"{key}: нужна HTTPS-ссылка на {host}")
    sections = re.fullmatch(r"## Статья и подписка\s*\n(.+?)\n## Только подписка\s*\n(.+)", match[2].strip(), re.S)
    if sections is None:
        raise HTTPException(422, "Сохраните разделы «Статья и подписка» и «Только подписка»")
    variants = {}
    footer = ""
    for key, text in zip(("full", "subscribe"), sections.groups()):
        text = text.strip()
        if not text or len(text) > 5000:
            raise HTTPException(422, "Каждый текст блока должен содержать от 1 до 5000 символов")
        if key == "full":
            text, _, footer = text.partition("\n\n")
        variants[key] = inline_markdown(text)
    return {"html": '<p class="reader-channel-copy">' + variants["full"] + '</p>',
            "variants": variants, "footer_html": inline_markdown(footer.strip()), "settings": settings}


def reader_subscription_document(db: Session) -> ManagedDocumentVersion:
    return active_public_site_document(db, "reader-subscription")


def render_reader_subscription(db: Session, template: str, *, popup: bool = True) -> str:
    payload = reader_subscription_document(db).payload
    settings = payload["settings"]
    values = {
        "READER_COPY": payload["html"],
        "READER_FOOTER": payload.get("footer_html", ""),
        "READER_FOOTER_HIDDEN": "" if payload.get("footer_html") else "hidden",
        "READER_TELEGRAM": escape(settings["telegram_url"], quote=True),
        "READER_MAX": escape(settings["max_url"], quote=True),
    }
    card = re.sub(r"\{\{(READER_COPY|READER_TELEGRAM|READER_MAX|READER_FOOTER|READER_FOOTER_HIDDEN)\}\}", lambda match: values[match[1]], template)
    if not popup:
        return card.replace('<section class="reader-channel blog-cta">',
                            '<section id="reader-channel-homepage" class="reader-channel blog-cta" hidden>')
    return ('<dialog id="reader-popup" aria-label="Приглашение читать мои посты">'
            '<button class="reader-close" type="button" aria-label="Закрыть приглашение">×</button>'
            + card + '</dialog>')


def document_definition(slug: str) -> dict:
    definition = DOCUMENTS.get(slug)
    if definition is None:
        raise HTTPException(404, "Документ публичного сайта не найден")
    return definition


def seed_markdown(slug: str) -> str:
    definition = document_definition(slug)
    return (CONTENT_ROOT / definition["file"]).read_text(encoding="utf-8").strip()


def normalize_payload(slug: str, payload: dict) -> dict:
    definition = document_definition(slug)
    markdown = str(payload.get("markdown") or "").replace("\r", "").strip()
    if not markdown:
        raise HTTPException(422, "Markdown-документ не может быть пустым")
    if len(markdown) > 250_000:
        raise HTTPException(422, "Markdown-документ слишком большой")
    rendered = render_document(slug, markdown)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "slug": slug,
        "title": definition["title"],
        "kind": definition["kind"],
        "markdown": markdown,
        "html": rendered["html"],
        "items": rendered.get("items", []),
    }
    if definition["kind"] == "reader-subscription":
        result["settings"] = rendered["settings"]
        result["variants"] = rendered["variants"]
        result["footer_html"] = rendered["footer_html"]
    return result


def render_faq(markdown: str) -> dict:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", markdown))
    if not matches:
        raise HTTPException(422, "FAQ должен содержать вопросы второго уровня: ## Вопрос")
    items = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[body_start:body_end].strip()
        if not body:
            raise HTTPException(422, f"У вопроса «{match.group(1).strip()}» нет ответа")
        items.append(
            {
                "question": match.group(1).strip(),
                "html": markdown_to_article_html(body),
            }
        )
    return {"html": "", "items": items}


def render_document(slug: str, markdown: str) -> dict:
    definition = document_definition(slug)
    if definition["kind"] == "faq":
        return render_faq(markdown)
    if definition["kind"] == "reader-subscription":
        return render_reader_subscription_source(markdown)
    return {"html": markdown_to_article_html(markdown), "items": []}


def ensure_public_site_document(db: Session, slug: str) -> ManagedDocumentVersion:
    definition = document_definition(slug)
    payload = normalize_payload(slug, {"markdown": seed_markdown(slug)})
    return ensure_seed_document(
        db,
        document_type=DOCUMENT_TYPE,
        document_key=slug,
        schema_version=SCHEMA_VERSION,
        payload=payload,
    )


def active_public_site_document(db: Session, slug: str) -> ManagedDocumentVersion:
    document_definition(slug)
    return active_document(db, DOCUMENT_TYPE, slug) or ensure_public_site_document(db, slug)


def serialize_public_site_document(version: ManagedDocumentVersion) -> dict:
    result = deepcopy(version.payload)
    result.update(
        {
            "version": version.version_no,
            "updated_at": version.created_at.isoformat(),
            "updated_by": version.created_by,
        }
    )
    return result


def serialize_public_site_rendered_document(version: ManagedDocumentVersion) -> dict:
    payload = version.payload
    return {
        "schemaVersion": payload["schemaVersion"],
        "slug": payload["slug"],
        "title": payload["title"],
        "kind": payload["kind"],
        "html": relative_site_html(payload["html"]),
        "items": [{**item, "html": relative_site_html(item["html"])}
                  for item in payload.get("items", [])],
        "version": version.version_no,
        "updated_at": version.created_at.isoformat(),
    }


def publish_public_site_document(
    db: Session,
    *,
    slug: str,
    markdown: str,
    expected_version: int,
    admin: str,
) -> ManagedDocumentVersion:
    active_public_site_document(db, slug)
    from app.editorial_media import markdown_media
    markdown_media(db, "public:" + slug, markdown)
    markdown = VERSION_MARKER.sub("", markdown, count=1).lstrip()
    markdown = f"<!-- public-site-version: {expected_version + 1} -->\n\n{markdown}"
    return publish_document(
        db,
        document_type=DOCUMENT_TYPE,
        document_key=slug,
        schema_version=SCHEMA_VERSION,
        payload=normalize_payload(slug, {"markdown": markdown}),
        expected_version=expected_version,
        admin=admin,
    )
