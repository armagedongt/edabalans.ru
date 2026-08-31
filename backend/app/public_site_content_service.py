from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.article_markup import markdown_to_article_html
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
}


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
    return {
        "schemaVersion": SCHEMA_VERSION,
        "slug": slug,
        "title": definition["title"],
        "kind": definition["kind"],
        "markdown": markdown,
        "html": rendered["html"],
        "items": rendered.get("items", []),
    }


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
        "html": payload["html"],
        "items": deepcopy(payload.get("items", [])),
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
