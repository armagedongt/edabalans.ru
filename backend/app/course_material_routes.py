from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.course_material_service import (
    checked_course,
    get_material,
    list_materials,
    material_versions,
    publish_material,
    restore_material,
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


def component_asset(*parts: str) -> str:
    return COURSE_CONTENT_ROOT.joinpath("components", *parts).read_text(encoding="utf-8")


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
    restorer = restore_material if service is None else service.restore_material
    return restorer(
        db,
        step_id=step_id,
        version_no=version_no,
        expected_version=body.expected_version,
        admin=admin,
    )
