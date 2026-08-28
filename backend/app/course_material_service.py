from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.article_markup import (
    article_plain_text,
    markdown_to_article_html,
    sanitize_article_html,
)
from app.course_structure_service import (
    COURSE_CONTENT_ROOT,
    DOCUMENT_KEY,
    CourseContext,
    course_context,
)
from app.models import ContentItem, ContentItemVersion, ContentSource
from app.masterclass_article_components import render_masterclass_component


SOURCE_PLATFORM = "internal"
SOURCE_ACCOUNT_KEY = "masterclass-course-materials"
PARSER_VERSION = "masterclass-material-v2"
MAX_MATERIAL_BYTES = 500_000


def checked_course(course_code: str) -> str:
    if course_code != DOCUMENT_KEY:
        raise HTTPException(404, "Курс не найден")
    return course_code


def article_step(context: CourseContext, step_id: str) -> tuple[int, dict]:
    for day_number, day in context.days.items():
        for step in day.get("steps", []):
            if step.get("id") != step_id:
                continue
            if step.get("kind") != "article" or step.get("contentKind") == "tutorial":
                raise HTTPException(
                    422,
                    "Этот материал является специальным модулем и не публикуется как статья",
                )
            return day_number, step
    raise HTTPException(404, "Материал курса не найден")


def material_source(db: Session, *, create: bool = False) -> ContentSource | None:
    source = db.scalar(
        select(ContentSource).where(
            ContentSource.platform == SOURCE_PLATFORM,
            ContentSource.account_key == SOURCE_ACCOUNT_KEY,
        )
    )
    if source is None and create:
        source = ContentSource(
            platform=SOURCE_PLATFORM,
            account_key=SOURCE_ACCOUNT_KEY,
            display_name="Материалы Мастер-класса",
            canonical_url="https://app.edabalans.ru/apps/masterclass-course.html",
        )
        db.add(source)
        db.flush()
    return source


def material_item(
    db: Session, step_id: str, *, for_update: bool = False
) -> ContentItem | None:
    source = material_source(db)
    if source is None:
        return None
    statement = select(ContentItem).where(
        ContentItem.source_id == source.id,
        ContentItem.external_id == step_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def latest_version(db: Session, item: ContentItem | None) -> ContentItemVersion | None:
    if item is None or item.latest_version_id is None:
        return None
    return db.get(ContentItemVersion, item.latest_version_id)


def word_count(html: str) -> int:
    return len(article_plain_text(html).split())


def version_payload(
    step_id: str,
    day_number: int,
    step: dict,
    version: ContentItemVersion | None,
    *,
    fallback_html: str = "",
) -> dict:
    html = version.text_content if version else fallback_html
    return {
        "ok": True,
        "course_code": DOCUMENT_KEY,
        "step_id": step_id,
        "day": day_number,
        "title": step.get("title") or step.get("label") or "",
        "summary": step.get("summary") or "",
        "version": version.version_no if version else 0,
        "published": version is not None,
        "html": html,
        "word_count": word_count(html),
        "updated_at": version.imported_at.isoformat() if version else None,
        "format": "semantic_html",
    }


def legacy_material_html(step: dict) -> str:
    asset = step.get("contentAsset")
    if asset == "extracted-2026-08-23.json":
        path = COURSE_CONTENT_ROOT / "imported-draft" / str(asset)
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            page_title = step.get("contentPageTitle") or step.get("title")
            page = next(
                (item for item in payload.get("pages", []) if item.get("title") == page_title),
                None,
            )
            if page and page.get("rich_html"):
                return str(page["rich_html"])
    elif asset:
        path = COURSE_CONTENT_ROOT / "source-current" / str(asset)
        if path.is_file():
            return markdown_to_article_html(
                path.read_text(encoding="utf-8"),
                strip_source_metadata=True,
                component_renderer=render_masterclass_component,
            )
    summary = str(step.get("summary") or "").strip()
    return f"<p>{summary}</p>" if summary else ""


def get_material(db: Session, step_id: str) -> dict:
    context = course_context(db)
    day_number, step = article_step(context, step_id)
    version = latest_version(db, material_item(db, step_id))
    return version_payload(
        step_id,
        day_number,
        step,
        version,
        fallback_html=legacy_material_html(step) if version is None else "",
    )


def list_materials(db: Session) -> dict:
    context = course_context(db)
    source = material_source(db)
    versions: dict[str, ContentItemVersion] = {}
    if source is not None:
        rows = db.execute(
            select(ContentItem, ContentItemVersion)
            .join(ContentItemVersion, ContentItemVersion.id == ContentItem.latest_version_id)
            .where(ContentItem.source_id == source.id)
        ).all()
        versions = {item.external_id: version for item, version in rows}
    materials = []
    for day_number, day in context.days.items():
        for step in day.get("steps", []):
            if step.get("kind") != "article" or step.get("contentKind") == "tutorial":
                continue
            version = versions.get(step["id"])
            materials.append({
                "step_id": step["id"],
                "day": day_number,
                "title": step.get("title") or step.get("label") or "",
                "summary": step.get("summary") or "",
                "content_kind": step.get("contentKind") or "text",
                "version": version.version_no if version else 0,
                "published": version is not None,
                "updated_at": version.imported_at.isoformat() if version else None,
            })
    return {"ok": True, "course_code": DOCUMENT_KEY, "materials": materials}


def render_material(content: str, content_format: str) -> str:
    if len(content.encode("utf-8")) > MAX_MATERIAL_BYTES:
        raise HTTPException(413, "Текст материала превышает допустимый размер")
    if content_format == "markdown":
        return markdown_to_article_html(
            content, component_renderer=render_masterclass_component
        )
    if content_format == "html":
        return sanitize_article_html(
            content, allow_h1=False, course_semantics=True
        )
    if content_format == "trusted_component_html":
        return sanitize_article_html(
            content,
            allow_h1=False,
            course_semantics=True,
            allow_product_components=True,
        )
    raise HTTPException(422, "Формат материала должен быть markdown или html")


def material_hash(step_id: str, version_no: int, html: str) -> str:
    return hashlib.sha256(f"{step_id}\0{version_no}\0{html}".encode()).hexdigest()


def publish_material(
    db: Session,
    *,
    step_id: str,
    content: str,
    content_format: str,
    expected_version: int,
    admin: str,
) -> dict:
    context = course_context(db)
    day_number, step = article_step(context, step_id)
    clean_html = render_material(content, content_format)
    try:
        source = material_source(db, create=True)
        item = material_item(db, step_id, for_update=True)
        current = latest_version(db, item)
        current_version = current.version_no if current else 0
        if current_version != expected_version:
            raise HTTPException(
                409,
                "Материал уже изменён. Получите актуальную версию перед публикацией",
            )
        if current and current.text_content == clean_html:
            return version_payload(step_id, day_number, step, current)
        if item is None:
            item = ContentItem(
                source_id=source.id,
                external_id=step_id,
                canonical_url=(
                    "https://app.edabalans.ru/apps/masterclass-course.html"
                    f"?course_day={day_number}&course_material={step_id}"
                ),
                title=step.get("title") or step.get("label") or step_id,
                author_name=admin,
                published_at=datetime.now(timezone.utc),
                status="published",
                source_tags=["masterclass", "course-material", f"day-{day_number}"],
                review_status="approved",
            )
            db.add(item)
            db.flush()
        else:
            item.title = step.get("title") or step.get("label") or item.title
            item.status = "published"
            item.source_updated_at = datetime.now(timezone.utc)
        next_version = current_version + 1
        version = ContentItemVersion(
            item_id=item.id,
            version_no=next_version,
            content_hash=material_hash(step_id, next_version, clean_html),
            text_content=clean_html,
            blocks=[{"type": "article_html", "html": clean_html}],
            parser_version=PARSER_VERSION,
            source_updated_at=datetime.now(timezone.utc),
        )
        db.add(version)
        db.flush()
        item.latest_version_id = version.id
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            "Материал уже изменён. Получите актуальную версию перед публикацией",
        ) from exc
    db.refresh(version)
    return version_payload(step_id, day_number, step, version)


def material_versions(db: Session, step_id: str) -> dict:
    context = course_context(db)
    _, step = article_step(context, step_id)
    item = material_item(db, step_id)
    current = latest_version(db, item)
    rows = [] if item is None else list(
        db.scalars(
            select(ContentItemVersion)
            .where(ContentItemVersion.item_id == item.id)
            .order_by(ContentItemVersion.version_no.desc())
        )
    )
    return {
        "ok": True,
        "step_id": step_id,
        "title": step.get("title") or step.get("label") or "",
        "active_version": current.version_no if current else 0,
        "versions": [
            {
                "version": row.version_no,
                "updated_at": row.imported_at.isoformat(),
                "word_count": word_count(row.text_content),
                "active": bool(current and row.id == current.id),
            }
            for row in rows
        ],
    }


def restore_material(
    db: Session,
    *,
    step_id: str,
    version_no: int,
    expected_version: int,
    admin: str,
) -> dict:
    item = material_item(db, step_id)
    if item is None:
        raise HTTPException(404, "Редакция материала не найдена")
    source = db.scalar(
        select(ContentItemVersion).where(
            ContentItemVersion.item_id == item.id,
            ContentItemVersion.version_no == version_no,
        )
    )
    if source is None:
        raise HTTPException(404, "Редакция материала не найдена")
    return publish_material(
        db,
        step_id=step_id,
        content=source.text_content,
        content_format="trusted_component_html",
        expected_version=expected_version,
        admin=admin,
    )


def published_materials(db: Session, *, allowed_days: set[int]) -> dict:
    context = course_context(db)
    allowed = {
        step["id"]: (day_number, step)
        for day_number, day in context.days.items()
        for step in day.get("steps", [])
        if day_number in allowed_days
        and not step.get("hidden", False)
        and not step.get("locked", False)
        and step.get("kind") == "article"
        and step.get("contentKind") != "tutorial"
    }
    source = material_source(db)
    if source is None:
        return {"ok": True, "materials": {}}
    rows = db.execute(
        select(ContentItem, ContentItemVersion)
        .join(ContentItemVersion, ContentItemVersion.id == ContentItem.latest_version_id)
        .where(ContentItem.source_id == source.id)
    ).all()
    materials = {}
    for item, version in rows:
        target = allowed.get(item.external_id)
        if target is None:
            continue
        day_number, step = target
        materials[item.external_id] = version_payload(
            item.external_id, day_number, step, version
        )
    return {"ok": True, "materials": materials}
