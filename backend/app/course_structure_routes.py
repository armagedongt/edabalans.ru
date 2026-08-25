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
from app.database import get_db
from app.managed_documents import restore_document, version_history


router = APIRouter(tags=["course-structure-editor"])


class CourseStructureUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    manifest: dict


class CourseStructureRestore(BaseModel):
    expected_version: int = Field(ge=1)


def checked_course(course_code: str) -> str:
    if course_code != DOCUMENT_KEY:
        raise HTTPException(404, "Курс не найден")
    return course_code


def editor_payload(db: Session) -> dict:
    active = active_course_version(db)
    active_data = serialize_version(active)
    active_data["manifest"] = runtime_manifest(active.payload)
    return {
        "ok": True,
        "course": {
            "code": DOCUMENT_KEY,
            "name": "Мастер-класс",
            "days": len(active.payload.get("days", [])),
        },
        "active": active_data,
        "history": [
            serialize_version(version, include_payload=False)
            for version in version_history(db, DOCUMENT_TYPE, DOCUMENT_KEY)
        ],
    }


@router.get("/admin/api/courses")
def admin_courses(
    _: str = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    active = active_course_version(db)
    return {
        "ok": True,
        "courses": [{
            "code": DOCUMENT_KEY,
            "name": "Мастер-класс",
            "days": len(active.payload.get("days", [])),
            "version": active.version_no,
            "editor_url": f"/admin/courses/{DOCUMENT_KEY}/structure",
        }],
    }


@router.get("/admin/api/courses/{course_code}/structure")
def admin_course_structure(
    course_code: str,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    checked_course(course_code)
    return editor_payload(db)


@router.put("/admin/api/courses/{course_code}/structure")
def admin_save_course_structure(
    course_code: str,
    body: CourseStructureUpdate,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    checked_course(course_code)
    publish_course_structure(
        db,
        manifest=body.manifest,
        expected_version=body.expected_version,
        admin=admin,
    )
    return editor_payload(db)


@router.post("/admin/api/courses/{course_code}/structure/versions/{version_no}/restore")
def admin_restore_course_structure(
    course_code: str,
    version_no: int,
    body: CourseStructureRestore,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    checked_course(course_code)
    restore_document(
        db,
        document_type=DOCUMENT_TYPE,
        document_key=DOCUMENT_KEY,
        version_no=version_no,
        expected_version=body.expected_version,
        admin=admin,
        prepare_payload=prepare_restore_payload,
    )
    return editor_payload(db)
