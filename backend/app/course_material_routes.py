from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
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
from app.database import get_db
from app import calorie_course_material_service
from app.calorie_course_service import DOCUMENT_KEY as CALORIE_COURSE_CODE


def material_service(course_code: str):
    if course_code == CALORIE_COURSE_CODE:
        return calorie_course_material_service
    checked_course(course_code)
    return None


router = APIRouter(tags=["course-material-publisher"])


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
