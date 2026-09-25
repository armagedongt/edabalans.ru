from __future__ import annotations

from pathlib import Path
import difflib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.course_material_service import (
    article_step,
    checked_course,
    get_material,
    list_materials,
    material_versions,
    publish_material,
    restore_material,
    render_material,
)
from app.course_structure_service import course_context
from app.github_content_editor import GitHubContentEditor
from app.masterclass_editorial import (
    EDITABLE_MATERIALS,
    editorial_body_text,
    validate_editorial_source,
)
from app import calorie_course_material_service
from app.calorie_course_service import DOCUMENT_KEY as CALORIE_COURSE_CODE
from app.course_structure_service import COURSE_CONTENT_ROOT
from app.database import get_db


def material_service(course_code: str):
    if course_code == CALORIE_COURSE_CODE:
        return calorie_course_material_service
    checked_course(course_code)
    return None


router = APIRouter(tags=["course-material-publisher"])
MASTERCLASS_MEDIA_ROOTS = (
    (COURSE_CONTENT_ROOT / "editorial" / "assets").resolve(),
    (COURSE_CONTENT_ROOT / "source-current" / "assets").resolve(),
)
MASTERCLASS_MEDIA_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}


def component_asset(*parts: str) -> str:
    return COURSE_CONTENT_ROOT.joinpath("components", *parts).read_text(encoding="utf-8")


@router.get("/course-assets/masterclass/media/{asset_path:path}", include_in_schema=False)
def masterclass_article_media(asset_path: str) -> FileResponse:
    for root in MASTERCLASS_MEDIA_ROOTS:
        path = (root / asset_path).resolve()
        if (
            path.is_relative_to(root)
            and path.suffix.casefold() in MASTERCLASS_MEDIA_SUFFIXES
            and path.is_file()
        ):
            return FileResponse(
                path,
                media_type="image/webp" if path.suffix.casefold() == ".webp" else None,
                headers={"Cache-Control": "public, max-age=86400"},
            )
    raise HTTPException(404, "Изображение материала не найдено")


@router.get("/course-assets/masterclass/article-components.css", include_in_schema=False)
def masterclass_article_component_styles() -> Response:
    css = "\n".join((
        component_asset("dqs-image-slider", "slider.css"),
        component_asset("dqs-score-tables", "score-tables.css"),
        component_asset("article-spoiler", "spoiler.css"),
    ))
    return Response(
        css,
        media_type="text/css",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/course-assets/masterclass/article-components.js", include_in_schema=False)
def masterclass_article_component_script() -> Response:
    return Response(
        component_asset("dqs-image-slider", "slider.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


class CourseMaterialUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=500_000)
    format: Literal["markdown", "html"] = "markdown"


class CourseMaterialRestore(BaseModel):
    expected_version: int = Field(ge=1)


class EditorialPreview(BaseModel):
    content: str = Field(min_length=1, max_length=500_000)


class EditorialDraftSave(EditorialPreview):
    expected_main_sha: str = Field(min_length=7, max_length=128)
    expected_draft_sha: str | None = Field(default=None, min_length=7, max_length=128)


class EditorialPublish(BaseModel):
    expected_main_sha: str = Field(min_length=7, max_length=128)
    expected_draft_sha: str = Field(min_length=7, max_length=128)


class EditorialRollback(BaseModel):
    commit_sha: str = Field(min_length=7, max_length=128)
    expected_main_sha: str = Field(min_length=7, max_length=128)


def editorial_editor() -> GitHubContentEditor:
    return GitHubContentEditor()


def editorial_title(db: Session, step_id: str) -> tuple[int, str]:
    try:
        day, step = article_step(course_context(db), step_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return day, str(step.get("title") or step.get("label") or step_id)


@router.get("/admin/api/editorial/masterclass/materials/{step_id}")
def admin_editorial_material(
    step_id: str,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    day, title = editorial_title(db, step_id)
    try:
        payload = editorial_editor().load(step_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {**payload, "day": day, "title": title}


@router.post("/admin/api/editorial/masterclass/materials/{step_id}/preview")
def admin_editorial_preview(
    step_id: str,
    body: EditorialPreview,
    _: str = Depends(require_admin),
) -> dict:
    try:
        current = editorial_editor().load(step_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        warnings = validate_editorial_source(step_id, body.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    html = render_material(editorial_body_text(body.content), "markdown")
    diff = "\n".join(
        difflib.unified_diff(
            current["main"]["content"].splitlines(),
            body.content.splitlines(),
            fromfile="опубликовано",
            tofile="редактор",
            lineterm="",
        )
    )
    return {"ok": True, "html": html, "diff": diff, "warnings": warnings}


@router.put("/admin/api/editorial/masterclass/materials/{step_id}/draft")
def admin_editorial_save_draft(
    step_id: str,
    body: EditorialDraftSave,
    admin: str = Depends(require_admin),
) -> dict:
    try:
        validate_editorial_source(step_id, body.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        return editorial_editor().save_draft(
            step_id,
            content=body.content,
            expected_main_sha=body.expected_main_sha,
            expected_draft_sha=body.expected_draft_sha,
            admin=admin,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/admin/api/editorial/masterclass/materials/{step_id}/publish")
def admin_editorial_publish(
    step_id: str,
    body: EditorialPublish,
    admin: str = Depends(require_admin),
) -> dict:
    try:
        return editorial_editor().publish(
            step_id,
            expected_main_sha=body.expected_main_sha,
            expected_draft_sha=body.expected_draft_sha,
            admin=admin,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/admin/api/editorial/masterclass/materials/{step_id}/history")
def admin_editorial_history(
    step_id: str, _: str = Depends(require_admin)
) -> dict:
    try:
        return editorial_editor().history(step_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/admin/api/editorial/masterclass/materials/{step_id}/rollback")
def admin_editorial_rollback(
    step_id: str,
    body: EditorialRollback,
    admin: str = Depends(require_admin),
) -> dict:
    try:
        return editorial_editor().rollback(
            step_id,
            commit_sha=body.commit_sha,
            expected_main_sha=body.expected_main_sha,
            admin=admin,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/admin/api/courses/{course_code}/materials")
def admin_course_materials(
    course_code: str,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    service = material_service(course_code)
    return list_materials(db) if service is None else service.list_materials(db)


@router.get("/admin/api/courses/{course_code}/materials/{step_id}")
def admin_course_material(
    course_code: str,
    step_id: str,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    service = material_service(course_code)
    return get_material(db, step_id) if service is None else service.get_material(db, step_id)


@router.put("/admin/api/courses/{course_code}/materials/{step_id}")
def admin_publish_course_material(
    course_code: str,
    step_id: str,
    body: CourseMaterialUpdate,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    service = material_service(course_code)
    if service is None and step_id in EDITABLE_MATERIALS:
        raise HTTPException(
            409,
            "Этот материал управляется каноническим Markdown-файлом. Используйте новый редактор материала",
        )
    publisher = publish_material if service is None else service.publish_material
    return publisher(
        db,
        step_id=step_id,
        content=body.content,
        content_format=body.format,
        expected_version=body.expected_version,
        admin=admin,
    )
@router.get("/admin/api/courses/{course_code}/materials/{step_id}/versions")
def admin_course_material_versions(
    course_code: str,
    step_id: str,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    service = material_service(course_code)
    return (
        material_versions(db, step_id)
        if service is None
        else service.material_versions(db, step_id)
    )


@router.post(
    "/admin/api/courses/{course_code}/materials/{step_id}/versions/{version_no}/restore"
)
def admin_restore_course_material(
    course_code: str,
    step_id: str,
    version_no: int,
    body: CourseMaterialRestore,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    service = material_service(course_code)
    if service is None and step_id in EDITABLE_MATERIALS:
        raise HTTPException(
            409,
            "Этот материал управляется каноническим Markdown-файлом. Используйте историю нового редактора",
        )
    restorer = restore_material if service is None else service.restore_material
    return restorer(
        db,
        step_id=step_id,
        version_no=version_no,
        expected_version=body.expected_version,
        admin=admin,
    )
