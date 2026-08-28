from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.article_markup import article_plain_text, markdown_to_article_html, sanitize_article_html
from app.calorie_course_service import DOCUMENT_KEY, CalorieCourseContext, course_context
from app.models import ContentItem, ContentItemVersion, ContentSource


SOURCE_PLATFORM = "internal"
SOURCE_ACCOUNT_KEY = "calories-course-materials"
PARSER_VERSION = "calories-material-v1"
MAX_MATERIAL_BYTES = 500_000


def article_step(context: CalorieCourseContext, step_id: str) -> tuple[int, dict]:
    for stage_number, stage in context.stages.items():
        for step in stage.get("steps", []):
            if step.get("id") != step_id:
                continue
            if step.get("kind") != "article":
                raise HTTPException(422, "Этот шаг не публикуется как статья")
            return stage_number, step
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
            display_name="Материалы Калорийного курса",
            canonical_url="https://app.edabalans.ru/apps/calories-course.html",
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
    stage_number: int,
    step: dict,
    version: ContentItemVersion | None,
) -> dict:
    html = version.text_content if version else ""
    return {
        "ok": True,
        "course_code": DOCUMENT_KEY,
        "step_id": step_id,
        "stage": stage_number,
        "day": stage_number,
        "title": step.get("title") or "",
        "summary": step.get("summary") or "",
        "version": version.version_no if version else 0,
        "published": version is not None,
        "html": html,
        "word_count": word_count(html),
        "updated_at": version.imported_at.isoformat() if version else None,
        "format": "semantic_html",
    }


def get_material(db: Session, step_id: str) -> dict:
    context = course_context(db)
    stage_number, step = article_step(context, step_id)
    return version_payload(
        step_id, stage_number, step, latest_version(db, material_item(db, step_id))
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
    for stage_number, stage in context.stages.items():
        for step in stage.get("steps", []):
            if step.get("kind") != "article":
                continue
            version = versions.get(step["id"])
            materials.append(
                {
                    "step_id": step["id"],
                    "stage": stage_number,
                    "day": stage_number,
                    "title": step.get("title") or "",
                    "summary": step.get("summary") or "",
                    "content_kind": step.get("contentKind") or "text",
                    "version": version.version_no if version else 0,
                    "published": version is not None,
                    "updated_at": version.imported_at.isoformat() if version else None,
                }
            )
    return {"ok": True, "course_code": DOCUMENT_KEY, "materials": materials}


def publication_status(db: Session) -> dict:
    context = course_context(db)
    materials = list_materials(db)["materials"]
    visible = [item for item in materials if not article_step(context, item["step_id"])[1].get("hidden", False)]
    published = sum(1 for item in visible if item["published"])
    launch_ready = bool(context.manifest.get("launchReady", False))
    return {
        "total": len(visible),
        "published": published,
        "launch_ready": launch_ready,
        "ready": launch_ready and bool(visible) and published == len(visible),
    }


def render_material(content: str, content_format: str) -> str:
    if len(content.encode("utf-8")) > MAX_MATERIAL_BYTES:
        raise HTTPException(413, "Текст материала превышает допустимый размер")
    if content_format == "markdown":
        return markdown_to_article_html(content)
    if content_format == "html":
        return sanitize_article_html(content, allow_h1=False, course_semantics=True)
    raise HTTPException(422, "Формат материала должен быть markdown или html")


def material_hash(step_id: str, version_no: int, html: str) -> str:
    return hashlib.sha256(f"{DOCUMENT_KEY}\0{step_id}\0{version_no}\0{html}".encode()).hexdigest()


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
    stage_number, step = article_step(context, step_id)
    clean_html = render_material(content, content_format)
    try:
        source = material_source(db, create=True)
        item = material_item(db, step_id, for_update=True)
        current = latest_version(db, item)
        current_version = current.version_no if current else 0
        if current_version != expected_version:
            raise HTTPException(
                409, "Материал уже изменён. Получите актуальную версию перед публикацией"
            )
        if current and current.text_content == clean_html:
            return version_payload(step_id, stage_number, step, current)
        if item is None:
            item = ContentItem(
                source_id=source.id,
                external_id=step_id,
                canonical_url=(
                    "https://app.edabalans.ru/apps/calories-course.html"
                    f"?calories_stage={stage_number}&calories_material={step_id}"
                ),
                title=step.get("title") or step_id,
                author_name=admin,
                published_at=datetime.now(timezone.utc),
                status="published",
                source_tags=["calories", "course-material", f"stage-{stage_number}"],
                review_status="approved",
            )
            db.add(item)
            db.flush()
        else:
            item.title = step.get("title") or item.title
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
            409, "Материал уже изменён. Получите актуальную версию перед публикацией"
        ) from exc
    db.refresh(version)
    return version_payload(step_id, stage_number, step, version)


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
        "title": step.get("title") or "",
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
        content_format="html",
        expected_version=expected_version,
        admin=admin,
    )


def published_materials(db: Session, *, allowed_stages: set[int]) -> dict:
    context = course_context(db)
    allowed = {
        step["id"]: (stage_number, step)
        for stage_number, stage in context.stages.items()
        for step in stage.get("steps", [])
        if stage_number in allowed_stages
        and not step.get("hidden", False)
        and step.get("kind") == "article"
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
        stage_number, step = target
        materials[item.external_id] = version_payload(
            item.external_id, stage_number, step, version
        )
    return {"ok": True, "materials": materials}
