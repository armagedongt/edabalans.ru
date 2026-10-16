"""Isolated Mini App transition preview; no CRM writes or bot messages."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.account_auth_routes import messenger_init_user_id
from app.config import Settings, get_settings

router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parent / "static" / "channel-bridge"
# Public pinned post checked with getChat on 2026-10-17. This preview is fixed
# deliberately: arbitrary destinations are not accepted from URL parameters.
PREVIEW_POST_URL = "https://t.me/Fitness_Talks/260"
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
) -> JSONResponse:
    if not settings.telegram_test_bot_token:
        raise HTTPException(status_code=503, detail="Telegram verification unavailable")
    if messenger_init_user_id(body.init_data, settings.telegram_test_bot_token) is None:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")
    # Verify only. Opening the preview must not create an account, session,
    # attribution event, sequence run, or permission to send messages.
    return JSONResponse({"destination": PREVIEW_POST_URL}, headers=PRIVATE_HEADERS)
