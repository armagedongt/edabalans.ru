"""Guarded adoption of legacy course sources, using native version publishers."""
from __future__ import annotations

import hashlib
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth import require_admin
from app.database import get_db
from app import course_material_service as masterclass
from app import calorie_course_material_service as calories
from app.article_markdown_conversion import ConversionError, convert, preserved_html
from app.masterclass_editorial import EDITABLE_MATERIALS
from app.blog_draft_routes import require_blog_mutation, PRIVATE_HEADERS

router = APIRouter()


def service(course_code: str):
    if course_code == calories.DOCUMENT_KEY:
        return calories
    masterclass.checked_course(course_code)
    return masterclass


def preview(db: Session, course_code: str, step_id: str) -> dict:
    native = service(course_code)
    if native is masterclass and (step_id in EDITABLE_MATERIALS or step_id.startswith("day-15-recipe-")):
        raise HTTPException(422, "Этот оригинал использует специальный маршрут")
    current = native.get_material(db, step_id)
    if current["source_format"] == "markdown":
        return {"ok": True, "already_markdown": True, "material": current}
    html_hash = hashlib.sha256(current["html"].encode("utf-8")).hexdigest()
    profile = None
    candidate = None
    if native is masterclass:
        _, step = native.article_step(native.course_context(db), step_id)
        original = native.source_current_markdown(step)
        if original:
            try:
                preserved_html(current["html"], native.render_material(original, "markdown",
                               render_profile=native.SOURCE_CURRENT_PROFILE), html_hash)
                candidate, profile = original, native.SOURCE_CURRENT_PROFILE
            except HTTPException:
                pass
    try:
        markdown = candidate if candidate is not None else convert(current["html"])
        preserved_html(current["html"], native.render_material(markdown, "markdown",
                       **({"render_profile": profile} if native is masterclass else {})), html_hash)
    except (ConversionError, ValueError, KeyError, HTTPException) as exc:
        raise HTTPException(422, "Безопасная конверсия невозможна: " + str(getattr(exc, "detail", exc))) from exc
    return {"ok": True, "already_markdown": False, "expected_version": current["version"],
            "html_sha256": html_hash, "markdown": markdown, "render_profile": profile,
            "original_recovered": candidate is not None}


class Adoption(BaseModel):
    expected_version: int = Field(ge=0)
    expected_html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.get("/admin/api/courses/{course_code}/materials/{step_id}/markdown")
def preview_conversion(course_code: str, step_id: str, response: Response, _: str = Depends(require_admin),
                       db: Session = Depends(get_db)) -> dict:
    response.headers.update(PRIVATE_HEADERS)
    return preview(db, course_code, step_id)


@router.post("/admin/api/courses/{course_code}/materials/{step_id}/markdown")
def adopt_conversion(course_code: str, step_id: str, body: Adoption, response: Response,
                     admin: str = Depends(require_blog_mutation), db: Session = Depends(get_db)) -> dict:
    response.headers.update(PRIVATE_HEADERS)
    prepared = preview(db, course_code, step_id)
    if prepared["already_markdown"]:
        raise HTTPException(409, "Оригинал уже Markdown; обновите локальный файл")
    if (prepared["expected_version"] != body.expected_version
            or prepared["html_sha256"] != body.expected_html_sha256):
        raise HTTPException(409, "Материал изменён после просмотра конверсии")
    return service(course_code).publish_material(
        db, step_id=step_id, content=prepared["markdown"], content_format="markdown",
        expected_version=body.expected_version, admin=admin,
        _markdown_adoption={"html_hash": body.expected_html_sha256,
                            "render_profile": prepared["render_profile"]},
    )
