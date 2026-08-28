from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.course_structure_service import (
    DOCUMENT_KEY,
    DOCUMENT_TYPE,
    active_course_version,
    prepare_restore_payload,
    publish_course_structure,
    runtime_manifest,
    serialize_version,
)
from app import calorie_course_material_service, calorie_course_service
from app.database import get_db
from app.managed_documents import restore_document, version_history


router = APIRouter(tags=["course-structure-editor"])


class CourseStructureUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    manifest: dict


class CourseStructureRestore(BaseModel):
    expected_version: int = Field(ge=1)


def course_service(course_code: str):
    if course_code == DOCUMENT_KEY:
        return None
    if course_code == calorie_course_service.DOCUMENT_KEY:
        return calorie_course_service
    raise HTTPException(404, "Курс не найден")


def editor_payload(db: Session, course_code: str = DOCUMENT_KEY) -> dict:
    service = course_service(course_code)
    active = (
        active_course_version(db)
        if service is None
        else service.active_course_version(db)
    )
    serializer = serialize_version if service is None else service.serialize_version
    manifest_builder = runtime_manifest if service is None else service.runtime_manifest
    active_data = serializer(active)
    active_data["manifest"] = manifest_builder(active.payload)
    manifest = active_data["manifest"]
    unit_name = "день" if service is None else "этап"
    return {
        "ok": True,
        "course": {
            "code": course_code,
            "name": "Мастер-класс" if service is None else "Калорийный курс",
            "days": len(manifest.get("days", [])),
            "unit_name": unit_name,
        },
        "active": active_data,
        "history": [
            serializer(version, include_payload=False)
            for version in version_history(db, DOCUMENT_TYPE, course_code)
        ],
    }


@router.get("/admin/api/courses")
def admin_courses(
    _: str = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    active = active_course_version(db)
    calories = calorie_course_service.active_course_version(db)
    calories_status = calorie_course_material_service.publication_status(db)
    return {
        "ok": True,
        "courses": [
            {
                "code": DOCUMENT_KEY,
                "name": "Мастер-класс",
                "units": len(active.payload.get("days", [])),
                "unit_name": "дней",
                "version": active.version_no,
                "editor_url": f"/admin/courses/{DOCUMENT_KEY}/structure",
            },
            {
                "code": calorie_course_service.DOCUMENT_KEY,
                "name": "Калорийный курс",
                "units": len(calories.payload.get("stages", [])),
                "unit_name": "этапов",
                "version": calories.version_no,
                "editor_url": f"/admin/courses/{calorie_course_service.DOCUMENT_KEY}/structure",
                "materials_total": calories_status["total"],
                "materials_published": calories_status["published"],
                "launch_ready": calories_status["launch_ready"],
                "ready": calories_status["ready"],
            },
        ],
    }


@router.get("/admin/api/courses/{course_code}/structure")
def admin_course_structure(
    course_code: str,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    course_service(course_code)
    return editor_payload(db, course_code)
@router.put("/admin/api/courses/{course_code}/structure")
def admin_save_course_structure(
    course_code: str,
    body: CourseStructureUpdate,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    service = course_service(course_code)
    publisher = publish_course_structure if service is None else service.publish_course_structure
    publisher(db, manifest=body.manifest, expected_version=body.expected_version, admin=admin)
    return editor_payload(db, course_code)

@router.post("/admin/api/courses/{course_code}/structure/versions/{version_no}/restore")
def admin_restore_course_structure(
    course_code: str,
    version_no: int,
    body: CourseStructureRestore,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    service = course_service(course_code)
    restore_document(
        db,
        document_type=DOCUMENT_TYPE,
        document_key=course_code,
        version_no=version_no,
        expected_version=body.expected_version,
        admin=admin,
        prepare_payload=(
            prepare_restore_payload if service is None else service.prepare_restore_payload
        ),
    )
    return editor_payload(db, course_code)
