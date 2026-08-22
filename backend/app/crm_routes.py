from __future__ import annotations

import uuid
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import (
    ADMIN_COOKIE,
    ADMIN_SESSION_SECONDS,
    admin_identity,
    admin_session_token,
    require_admin,
    security,
    valid_admin_credentials,
)
from app.config import get_settings
from app.crm_service import (
    add_note,
    add_tag,
    list_tags,
    list_payments,
    list_users,
    summary,
    merge_tag,
    update_tag,
    update_user,
    user_detail,
    list_access_reviews,
    link_user_email,
    set_access_review,
    grant_manual_access,
    revoke_manual_access,
    list_resources,
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


class TagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=32)
    status: str = Field(min_length=1, max_length=32)


class TagMerge(BaseModel):
    target_name: str = Field(min_length=1, max_length=255)


class EmailLink(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class AccessReviewUpdate(BaseModel):
    status: str = Field(max_length=32)
    tilda_status: str = Field(max_length=32)
    note: str | None = Field(default=None, max_length=10_000)


class ResourceAction(BaseModel):
    resource_code: str = Field(min_length=1, max_length=80)


class AdminLogin(BaseModel):
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


def protected_file(name: str) -> FileResponse:
    response = FileResponse(STATIC_DIR / name)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/admin", include_in_schema=False)
@router.get("/admin/", include_in_schema=False)
def admin_index(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> FileResponse:
    return protected_file("admin.html" if admin_identity(request, credentials) else "admin-login.html")


@router.get("/admin/static/{asset_name}", include_in_schema=False)
def admin_asset(
    request: Request,
    asset_name: str = ApiPath(pattern="^(admin\\.css|admin\\.js|admin-session\\.css|admin-login\\.css|admin-login\\.js)$"),
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> FileResponse:
    if not asset_name.startswith("admin-login") and not admin_identity(request, credentials):
        raise HTTPException(status_code=401, detail="admin authentication required")
    return protected_file(asset_name)


@router.get("/admin/{section}", include_in_schema=False)
def admin_section(
    request: Request,
    section: str = ApiPath(pattern="^(users|crm|dqs|strength|metabolism|messaging)$"),
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> FileResponse:
    return protected_file("admin.html" if admin_identity(request, credentials) else "admin-login.html")


@router.post("/admin/api/login")
def admin_login(body: AdminLogin, response: Response) -> dict[str, bool]:
    if not valid_admin_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    settings = get_settings()
    expires_at = int(time.time()) + ADMIN_SESSION_SECONDS
    response.set_cookie(
        ADMIN_COOKIE,
        admin_session_token(settings.admin_username, expires_at),
        max_age=ADMIN_SESSION_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return {"ok": True}


@router.post("/admin/api/logout")
def admin_logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return {"ok": True}


@router.get("/crm", include_in_schema=False)
def crm_index(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> Response:
    if not admin_identity(request, credentials):
        return RedirectResponse("/admin?next=/crm", status_code=303)
    return protected_file("crm.html")


@router.get("/crm/crm.css", include_in_schema=False)
def crm_css(_: str = Depends(require_admin)) -> FileResponse:
    return protected_file("crm.css")


@router.get("/crm/crm.js", include_in_schema=False)
def crm_js(_: str = Depends(require_admin)) -> FileResponse:
    return protected_file("crm.js")


@router.get("/admin/api/audit/tags")
def admin_tag_audit(_: str = Depends(require_admin)) -> FileResponse:
    return protected_file("leadteh_tag_plan.json")


@router.get("/admin/api/audit/variables")
def admin_variable_audit(_: str = Depends(require_admin)) -> FileResponse:
    return protected_file("leadteh_variables.json")


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
    offset: int = Query(default=0, ge=0),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_users(db, query=q, buyers_only=buyers_only, limit=limit, offset=offset)


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


@router.get("/admin/api/access-reviews")
def admin_access_reviews(limit: int = Query(default=1000, ge=1, le=1000),
                         _: str = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    return list_access_reviews(db, limit)


@router.get("/admin/api/resources")
def admin_resources(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    return list_resources(db)


@router.post("/admin/api/users/{user_id}/email")
def admin_link_email(user_id: uuid.UUID, payload: EmailLink,
                     admin: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, str]:
    ok, result = link_user_email(db, user_id, payload.email, admin)
    if not ok:
        raise HTTPException(status_code=409 if result == "email_conflict" else 400, detail=result)
    return {"status": result}


@router.patch("/admin/api/users/{user_id}/access-review")
def admin_set_access_review(user_id: uuid.UUID, payload: AccessReviewUpdate,
                            admin: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, str]:
    if not set_access_review(db, user_id, payload.status, payload.tilda_status, payload.note, admin):
        raise HTTPException(status_code=400, detail="invalid review state or user")
    return {"status": "saved"}


@router.post("/admin/api/users/{user_id}/accesses")
def admin_grant_access(user_id: uuid.UUID, payload: ResourceAction,
                       admin: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, str]:
    if not grant_manual_access(db, user_id, payload.resource_code, admin):
        raise HTTPException(status_code=400, detail="user or resource not found")
    return {"status": "granted"}


@router.delete("/admin/api/users/{user_id}/accesses/{resource_code}")
def admin_revoke_access(user_id: uuid.UUID, resource_code: str,
                        admin: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, str]:
    if not revoke_manual_access(db, user_id, resource_code, admin):
        raise HTTPException(status_code=404, detail="active access not found")
    return {"status": "revoked"}


@router.get("/admin/api/payments")
def admin_payments(
    limit: int = Query(default=200, ge=1, le=500),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_payments(db, limit=limit)


@router.get("/admin/api/tags")
def admin_tags(
    q: str = Query(default="", max_length=255),
    category: str = Query(default="", max_length=32),
    status: str = Query(default="", max_length=32),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_tags(db, query=q, category=category, status=status)


@router.patch("/admin/api/tags/{tag_id}")
def admin_update_tag(
    tag_id: uuid.UUID,
    payload: TagUpdate,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not update_tag(db, tag_id, payload.name, payload.category, payload.status):
        raise HTTPException(status_code=400, detail="tag not found or invalid category/status")
    return {"status": "saved"}


@router.post("/admin/api/tags/{tag_id}/merge")
def admin_merge_tag(
    tag_id: uuid.UUID,
    payload: TagMerge,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not merge_tag(db, tag_id, payload.target_name):
        raise HTTPException(status_code=400, detail="target tag not found or invalid merge")
    return {"status": "merged"}
