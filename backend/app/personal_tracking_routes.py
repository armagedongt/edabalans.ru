from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.intensive_web_access import access_token_row
from app.models import AttributionEvent


router = APIRouter()


def _https_target(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc:
        raise HTTPException(status_code=503, detail="personal link target is not configured")
    return value


def _resolve_token(db: Session, token: str):
    row = access_token_row(db, token)
    if row is None:
        raise HTTPException(status_code=404, detail="personal link not found")
    return row


def _record(
    db: Session,
    request: Request,
    token_row,
    *,
    event_type: str,
    destination: str,
) -> None:
    query = request.query_params
    db.add(
        AttributionEvent(
            user_id=token_row.user_id,
            event_type=event_type,
            source_raw=token_row.platform,
            utm_source=query.get("utm_source"),
            utm_medium=query.get("utm_medium"),
            utm_campaign=query.get("utm_campaign"),
            utm_content=query.get("utm_content"),
            utm_term=query.get("utm_term"),
            ref_code=query.get("yclid") or query.get("alias"),
            landing_url=destination,
            occurred_at=datetime.now(timezone.utc),
        )
    )


def _redirect(target: str) -> RedirectResponse:
    response = RedirectResponse(target, status_code=307)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/m/{token}", include_in_schema=False)
def personal_masterclass_link(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    token_row = _resolve_token(db, token)
    target = _https_target(settings.personal_masterclass_target_url)
    _record(
        db,
        request,
        token_row,
        event_type="personal_masterclass_link_open",
        destination="masterclass_site",
    )
    db.commit()
    return _redirect(target)


@router.get("/p/{post_number}/{token}", include_in_schema=False)
def personal_channel_post_link(
    post_number: int,
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    if post_number < 1 or post_number > 9_999_999:
        raise HTTPException(status_code=404, detail="channel post not found")
    token_row = _resolve_token(db, token)
    if token_row.platform != "telegram":
        raise HTTPException(status_code=404, detail="channel post not found")
    base = _https_target(settings.telegram_channel_post_base_url).rstrip("/")
    target = f"{base}/{post_number}"
    _record(
        db,
        request,
        token_row,
        event_type="personal_channel_post_link_open",
        destination=f"telegram_post_{post_number}",
    )
    db.commit()
    return _redirect(target)
