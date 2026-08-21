from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.crm_service import (
    add_note,
    add_tag,
    list_payments,
    list_users,
    summary,
    update_user,
    user_detail,
)
from app.database import get_db

STATIC_DIR = Path(__file__).resolve().parent / "static"
router = APIRouter()


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


def protected_file(name: str) -> FileResponse:
    response = FileResponse(STATIC_DIR / name)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/crm", include_in_schema=False)
def crm_index(_: str = Depends(require_admin)) -> FileResponse:
    return protected_file("crm.html")


@router.get("/crm/crm.css", include_in_schema=False)
def crm_css(_: str = Depends(require_admin)) -> FileResponse:
    return protected_file("crm.css")


@router.get("/crm/crm.js", include_in_schema=False)
def crm_js(_: str = Depends(require_admin)) -> FileResponse:
    return protected_file("crm.js")


@router.get("/admin/api/summary")
def admin_summary(
    _: str = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    return summary(db)


@router.get("/admin/api/users")
def admin_users(
    q: str = Query(default="", max_length=255),
    buyers_only: bool = False,
    limit: int = Query(default=100, ge=1, le=250),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_users(db, query=q, buyers_only=buyers_only, limit=limit)


@router.get("/admin/api/users/{user_id}")
def admin_user(
    user_id: uuid.UUID,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    result = user_detail(db, user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="user not found")
    return result


@router.patch("/admin/api/users/{user_id}")
def admin_update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not update_user(db, user_id, payload.display_name):
        raise HTTPException(status_code=404, detail="user not found")
    return {"status": "saved"}


@router.post("/admin/api/users/{user_id}/notes", status_code=201)
def admin_add_note(
    user_id: uuid.UUID,
    payload: NoteCreate,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    note = add_note(db, user_id, payload.body, admin)
    if note is None:
        raise HTTPException(status_code=404, detail="user not found")
    return {"id": str(note.id), "status": "saved"}


@router.post("/admin/api/users/{user_id}/tags", status_code=201)
def admin_add_tag(
    user_id: uuid.UUID,
    payload: TagCreate,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not add_tag(db, user_id, payload.name):
        raise HTTPException(status_code=404, detail="user not found or invalid tag")
    return {"status": "saved"}


@router.get("/admin/api/payments")
def admin_payments(
    limit: int = Query(default=200, ge=1, le=500),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_payments(db, limit=limit)
