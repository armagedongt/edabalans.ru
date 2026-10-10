from pathlib import Path
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import Settings, get_settings
from app.database import get_db
from app.account_onboarding_service import _decrypt_bundle
from app.models import AdminAppEdit
from app import tilda_mailing_service as service

router = APIRouter()
STATIC = Path(__file__).resolve().parent / "static"


class DraftUpdate(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=20_000)
    included: bool


class Launch(BaseModel):
    expected_count: int = Field(ge=1, le=1000)
    confirm_send: bool


def same_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(403, "Откройте рассылку из этой админки")


@router.get("/admin/tilda-mailing", include_in_schema=False)
def page(request: Request):
    from app.auth import admin_identity
    if not admin_identity(request):
        return RedirectResponse("/admin?next=/admin/tilda-mailing", status_code=303)
    return FileResponse(STATIC / "tilda-mailing.html", headers={"Cache-Control": "no-store"})


@router.get("/admin/tilda-mailing/{asset}", include_in_schema=False)
def asset(asset: str, _: str = Depends(require_admin)):
    if asset not in {"tilda-mailing.js", "tilda-mailing.css"}:
        raise HTTPException(404)
    return FileResponse(STATIC / asset, headers={"Cache-Control": "no-store"})


@router.get("/admin/api/tilda-mailing")
def listing(_: str = Depends(require_admin), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return JSONResponse(service.listing(db, settings), headers={"Cache-Control": "no-store"})


@router.get("/admin/api/tilda-mailing/{delivery_id}")
def draft(delivery_id: uuid.UUID, admin: str = Depends(require_admin), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    try:
        row = service.get_draft(db, delivery_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    bundle = _decrypt_bundle(row.claim_bundle_encrypted, settings)
    db.add(AdminAppEdit(admin_username=admin, target_user_id=row.user_id, app_code="crm", action="view_tilda_letter", details={"delivery_id": str(row.id)}))
    db.commit()
    return JSONResponse({"id": str(row.id), "subject": bundle["subject"], "text": bundle["message_text"], "included": row.email_status == "draft", "editable": row.email_status in {"draft", "excluded"}}, headers={"Cache-Control": "no-store"})


@router.put("/admin/api/tilda-mailing/{delivery_id}", dependencies=[Depends(same_origin)])
def edit(delivery_id: uuid.UUID, body: DraftUpdate, admin: str = Depends(require_admin), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    try:
        service.update_draft(db, service.get_draft(db, delivery_id), settings, admin, body.subject, body.text, body.included)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {"saved": True}


@router.post("/admin/api/tilda-mailing/launch", dependencies=[Depends(same_origin)])
def launch(body: Launch, admin: str = Depends(require_admin), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    if not body.confirm_send:
        raise HTTPException(422, "Подтвердите отправку выбранных писем")
    try:
        count = service.launch(db, settings, admin, body.expected_count)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {"queued": count}
