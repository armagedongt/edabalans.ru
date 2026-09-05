from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.tilda_service import TildaPayloadError, process_tilda_payment

router = APIRouter(prefix="/integrations/tilda", tags=["integrations"])
MAX_BODY_BYTES = 256 * 1024


def flatten_form_values(values: dict[str, list[str]]) -> dict[str, Any]:
    return {
        key: items[0] if len(items) == 1 else items
        for key, items in values.items()
    }


@router.post("/payments")
async def tilda_payment(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if not settings.tilda_webhook_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tilda webhook is not configured",
        )
    supplied_token = request.headers.get("X-Tilda-Webhook-Token", "")
    if not secrets.compare_digest(supplied_token, settings.tilda_webhook_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid webhook token",
        )

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="payload is too large")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="form-encoded payload is required")
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="payload must be UTF-8") from exc
    payload = flatten_form_values(parse_qs(decoded, keep_blank_values=True))

    if payload.get("test") == "test":
        return {"status": "ok"}
    try:
        return process_tilda_payment(db, payload, settings)
    except TildaPayloadError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
