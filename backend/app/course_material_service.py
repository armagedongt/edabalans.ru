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
from app.masterclass_editorial import EDITABLE_MATERIALS, editable_material_path, editorial_body, local_editable_material


SOURCE_PLATFORM = "internal"
SOURCE_ACCOUNT_KEY = "masterclass-course-materials"
PARSER_VERSION = "masterclass-material-v2"
MAX_MATERIAL_BYTES = 500_000
SOURCE_CURRENT_PROFILE = "masterclass-source-current"


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
            canonical_url="https://edabalans.ru/apps/masterclass-course.html",
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


def editorial_source_payload(version: ContentItemVersion | None, fallback_html: str = "") -> dict:
    for block in (version.blocks or []) if version else []:
        if block.get("type") == "editorial_source" and block.get("format") in {"markdown", "html"}:
            return {
                "source_content": block["content"],
                "source_format": block["format"],
                "source_provenance": "editorial_source",
                **({"source_render_profile": SOURCE_CURRENT_PROFILE,
                    "source_hash": hashlib.sha256(block["content"].encode("utf-8")).hexdigest()}
                   if block.get("render_profile") == SOURCE_CURRENT_PROFILE else {}),
            }
    return {
        "source_content": version.text_content if version else fallback_html,
        "source_format": "html",
        "source_provenance": "legacy_html" if version else "fallback_html",
    }


def reader_material_payload(payload: dict) -> dict:
    return {
        key: value for key, value in payload.items()
        if not key.startswith("source_") and key != "publication_profile"
    }


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
        **editorial_source_payload(version, fallback_html),
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


def source_current_markdown(step: dict) -> str | None:
    if step["id"] in EDITABLE_MATERIALS or step["id"].startswith("day-15-recipe-"):
        return None
    asset = step.get("contentAsset")
    if asset in {None, "extracted-2026-08-23.json"}:
        return None
    path = COURSE_CONTENT_ROOT / "source-current" / str(asset)
    return path.read_text(encoding="utf-8") if path.is_file() else None


def get_material(db: Session, step_id: str) -> dict:
    context = course_context(db)
    day_number, step = article_step(context, step_id)
    version = latest_version(db, material_item(db, step_id))
    payload = version_payload(
        step_id,
        day_number,
        step,
        version,
        fallback_html=legacy_material_html(step) if version is None else "",
    )
    if version is None and step.get("contentAsset") not in {None, "extracted-2026-08-23.json"}:
        path = COURSE_CONTENT_ROOT / "source-current" / str(step["contentAsset"])
        if path.is_file():
            payload.update(
                source_content=path.read_text(encoding="utf-8"),
                source_format="markdown",
                source_provenance="git_markdown",
            )
            if source_current_markdown(step) is not None:
                payload.update(
                    source_render_profile=SOURCE_CURRENT_PROFILE,
                    source_hash=hashlib.sha256(payload["source_content"].encode("utf-8")).hexdigest(),
                )
    if step_id in EDITABLE_MATERIALS:
        html = render_material(editorial_body(local_editable_material(step_id)), "markdown")
        payload.update(
            html=html,
            word_count=word_count(html),
            published=True,
            source="git_markdown",
            source_content=local_editable_material(step_id).read_text(encoding="utf-8"),
            source_format="markdown",
            source_provenance="git_markdown",
        )
    profile = publication_profile(step, version)
    if profile:
        payload["publication_profile"] = profile
    return payload


def publication_profile(step: dict, version: ContentItemVersion | None) -> dict | None:
    step_id = step["id"]
    if step_id in EDITABLE_MATERIALS:
        path = editable_material_path(step_id)
        if step_id.startswith("day-07-recipe-"):
            return {"type": "archive", "source_path": path,
                    "reason": "Исторический оригинал; текущие рецепты используют day-15-recipe ID"}
        return {"type": "git", "api_path": f"/admin/api/editorial/masterclass/materials/{step_id}",
                "source_path": path}
    if (version is None and source_current_markdown(step) is not None
            or version is not None and editorial_source_payload(version).get("source_render_profile") == SOURCE_CURRENT_PROFILE):
        return {"type": "api", "render_profile": SOURCE_CURRENT_PROFILE}
    return None


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
            profile = publication_profile(step, version)
            materials.append({
                "step_id": step["id"],
                "day": day_number,
                "title": step.get("title") or step.get("label") or "",
                "summary": step.get("summary") or "",
                "content_kind": step.get("contentKind") or "text",
                "version": version.version_no if version else 0,
                "published": version is not None,
                "updated_at": version.imported_at.isoformat() if version else None,
                **({"publication_profile": profile} if profile else {}),
            })
    return {"ok": True, "course_code": DOCUMENT_KEY, "materials": materials}


def render_material(content: str, content_format: str, *, render_profile: str | None = None) -> str:
    if len(content.encode("utf-8")) > MAX_MATERIAL_BYTES:
        raise HTTPException(413, "Текст материала превышает допустимый размер")
    if content_format == "markdown":
        return markdown_to_article_html(
            content, component_renderer=render_masterclass_component,
            strip_source_metadata=render_profile == SOURCE_CURRENT_PROFILE,
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
    commit: bool = True,
    _restore_version: ContentItemVersion | None = None,
    expected_source_hash: str | None = None,
) -> dict:
    context = course_context(db)
    day_number, step = article_step(context, step_id)
    if content_format == "markdown":
        from app.editorial_media import markdown_media
        markdown_media(db, "course:masterclass-21:" + step_id, content)
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
        source_payload = editorial_source_payload(_restore_version) if _restore_version else {
            "source_content": content,
            "source_format": "html" if content_format == "trusted_component_html" else content_format,
        }
        render_profile = editorial_source_payload(_restore_version or current).get("source_render_profile")
        if _restore_version is None and current is None:
            fallback = source_current_markdown(step)
            if fallback is not None:
                if expected_source_hash != hashlib.sha256(fallback.encode("utf-8")).hexdigest():
                    raise HTTPException(409, "Исходный Markdown изменён. Получите актуальную версию и hash")
                render_profile = SOURCE_CURRENT_PROFILE
        if _restore_version is None and render_profile == SOURCE_CURRENT_PROFILE and content_format != "markdown":
            raise HTTPException(422, "Этот материал редактируется по полному оригиналу Markdown")
        clean_html = _restore_version.text_content if _restore_version else render_material(
            content, content_format, render_profile=render_profile,
        )
        source_block = {
            "type": "editorial_source", "content": source_payload["source_content"],
            "format": source_payload["source_format"],
            **({"render_profile": SOURCE_CURRENT_PROFILE} if render_profile == SOURCE_CURRENT_PROFILE else {}),
        }
        if (current and current.text_content == clean_html
                and any(block == source_block for block in (current.blocks or []))):
            return version_payload(step_id, day_number, step, current)
        if item is None:
            item = ContentItem(
                source_id=source.id,
                external_id=step_id,
                canonical_url=(
                    "https://edabalans.ru/apps/masterclass-course.html"
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
            blocks=[{"type": "article_html", "html": clean_html}, source_block],
            parser_version=PARSER_VERSION,
            source_updated_at=datetime.now(timezone.utc),
        )
        db.add(version)
        db.flush()
        item.latest_version_id = version.id
        if commit:
            db.commit()
        else:
            db.flush()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            "Материал уже изменён. Получите актуальную версию перед публикацией",
        ) from exc
    if commit:
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
        _restore_version=source,
    )


def published_materials(
    db: Session,
    *,
    allowed_days: set[int],
    step_id: str | None = None,
    allowed_step_ids: set[str] | None = None,
) -> dict:
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
        and (allowed_step_ids is None or step["id"] in allowed_step_ids)
        and (step_id is None or step["id"] == step_id)
    }
    source = material_source(db)
    if not allowed:
        return {"ok": True, "materials": {}}
    rows = []
    if source is not None:
        rows = db.execute(
            select(ContentItem, ContentItemVersion)
            .join(ContentItemVersion, ContentItemVersion.id == ContentItem.latest_version_id)
            .where(ContentItem.source_id == source.id)
            .where(ContentItem.external_id.in_(allowed))
        ).all()
    materials = {}
    for item, version in rows:
        target = allowed.get(item.external_id)
        if target is None:
            continue
        day_number, step = target
        materials[item.external_id] = reader_material_payload(version_payload(
            item.external_id, day_number, step, version
        ))
    for editable_step_id in EDITABLE_MATERIALS.keys() & allowed.keys():
        day_number, step = allowed[editable_step_id]
        current_version = latest_version(db, material_item(db, editable_step_id))
        html = render_material(
            editorial_body(local_editable_material(editable_step_id)), "markdown"
        )
        payload = version_payload(
            editable_step_id,
            day_number,
            step,
            current_version,
            fallback_html=html,
        )
        payload.update(
            html=html,
            word_count=word_count(html),
            published=True,
            source="git_markdown",
        )
        materials[editable_step_id] = reader_material_payload(payload)
    return {"ok": True, "materials": materials}
