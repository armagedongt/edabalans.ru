"""Verified Mini App entry to the channel; never starts a bot conversation."""

import json
from pathlib import Path
from typing import Literal
from sqlalchemy.orm import Session
from app.database import get_db
from app.channel_entry_service import DEFAULT_DESTINATION, record_observation

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.account_auth_routes import messenger_init_user_id
from app.config import Settings, get_settings

router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parent / "static" / "channel-bridge"
# Safe public fallback. A different owned-channel post can only come from verified settings.
PREVIEW_POST_URL = DEFAULT_DESTINATION

PRIVATE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
}


class BridgeVerificationIn(BaseModel):
    init_data: str = Field(min_length=20, max_length=8192)


@router.get("/apps/channel-bridge", include_in_schema=False)
@router.get("/apps/channel-bridge/", include_in_schema=False)
@router.get("/c", include_in_schema=False)
@router.get("/c/", include_in_schema=False)
def channel_bridge_preview() -> HTMLResponse:
    template = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(
        template.replace("{{DESTINATION_JSON}}", json.dumps(PREVIEW_POST_URL)).replace(
            "{{DESTINATION_URL}}", PREVIEW_POST_URL
        ),
        headers=PRIVATE_HEADERS,
    )


@router.get("/apps/channel-bridge/bridge.js", include_in_schema=False)
def channel_bridge_script() -> FileResponse:
    return FileResponse(STATIC_DIR / "bridge.js", headers=PRIVATE_HEADERS)


@router.post("/apps/channel-bridge/verify", include_in_schema=False)
def verify_channel_bridge(
    body: BridgeVerificationIn,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> JSONResponse:
    if not settings.telegram_test_bot_token:
        raise HTTPException(status_code=503, detail="Telegram verification unavailable")
    telegram_id = messenger_init_user_id(body.init_data, settings.telegram_test_bot_token)
    if telegram_id is None:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")
    result = record_observation(db, init_data=body.init_data, telegram_id=telegram_id, kind="channel_entry_open", username=settings.telegram_test_bot_username)
    return JSONResponse(result, headers=PRIVATE_HEADERS)


class BridgeEventIn(BridgeVerificationIn):
    event: Literal["channel_permission_requested", "channel_permission_result", "channel_permission_unavailable", "channel_open_requested"]
    granted: bool | None = None


@router.post("/apps/channel-bridge/event", include_in_schema=False, status_code=204)
def record_channel_bridge_event(body: BridgeEventIn, settings: Settings = Depends(get_settings), db: Session = Depends(get_db)):
    telegram_id = messenger_init_user_id(body.init_data, settings.telegram_test_bot_token)
    if telegram_id is None:
        raise HTTPException(401, "Invalid Telegram data")
    record_observation(db, init_data=body.init_data, telegram_id=telegram_id, kind=body.event, granted=body.granted, username=settings.telegram_test_bot_username)
    from fastapi import Response
    return Response(status_code=204, headers=PRIVATE_HEADERS)


@router.get("/apps/channel-bridge/card", include_in_schema=False)
def shared_channel_card():
    return channel_bridge_preview()


@router.post("/apps/channel-bridge/max/verify", include_in_schema=False)
def verify_max_channel_bridge(body: BridgeVerificationIn, settings: Settings = Depends(get_settings),
                              db: Session = Depends(get_db)):
    identity = messenger_init_user_id(body.init_data, settings.max_bot_token)
    if identity is None:
        raise HTTPException(401, "Invalid MAX data")
    return JSONResponse(record_observation(db, init_data=body.init_data, telegram_id=identity,
        kind="channel_entry_open", username=settings.max_bot_username, messenger="max"), headers=PRIVATE_HEADERS)


@router.post("/apps/channel-bridge/max/event", include_in_schema=False, status_code=204)
def max_channel_bridge_event(body: BridgeEventIn, settings: Settings = Depends(get_settings),
                            db: Session = Depends(get_db)):
    identity = messenger_init_user_id(body.init_data, settings.max_bot_token)
    if identity is None:
        raise HTTPException(401, "Invalid MAX data")
    if body.event != "channel_open_requested":
        raise HTTPException(422, "MAX does not request write access")
    record_observation(db, init_data=body.init_data, telegram_id=identity, kind=body.event,
                       username=settings.max_bot_username, messenger="max")
    from fastapi import Response
    return Response(status_code=204, headers=PRIVATE_HEADERS)


@router.get("/apps/channel-bridge/max.js", include_in_schema=False)
def max_channel_bridge_script():
    return FileResponse(STATIC_DIR / "max.js", headers=PRIVATE_HEADERS)
