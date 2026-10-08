from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.browser_journey_service import (
    COOKIE_NAME, RETENTION, bind_personal, issue_context, public_host,
    record_browser_event, resolve_browser,
)
from app.config import Settings, get_settings
from app.database import get_db
from app.public_homepage_analytics_routes import enforce_rate_limit

router = APIRouter()


class BrowserEventIn(BaseModel):
    context: str | None = Field(default=None, max_length=512)
    transfer: str | None = Field(default=None, max_length=512)
    personal_token: str | None = Field(default=None, max_length=128)
    source_context: str | None = Field(default=None, max_length=160)
    event: Literal["init", "page", "action"] = "init"
    page_url: str = Field(default="", max_length=1500)
    action: str | None = Field(default=None, max_length=80)
    accepted: bool = False
    attribution: dict[Annotated[str, StringConstraints(max_length=64)],
                      Annotated[str, StringConstraints(max_length=512)]] = Field(default_factory=dict, max_length=8)


@router.get("/browser-journey.js", include_in_schema=False)
def browser_journey_script():
    return FileResponse(Path(__file__).with_name("static") / "browser-journey.js",
                        media_type="application/javascript; charset=utf-8", headers={"Cache-Control": "no-cache"})


@router.post("/api/public/browser-journey", include_in_schema=False)
def browser_journey_event(body: BrowserEventIn, request: Request, response: Response,
                          db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    enforce_rate_limit(request)
    if not settings.app_auth_secret:
        raise HTTPException(503, "Browser context is unavailable")
    origin = request.headers.get("origin")
    if origin:
        from urllib.parse import urlsplit
        if not public_host(urlsplit(origin).hostname or ""):
            raise HTTPException(403, "Browser origin rejected")
    row = resolve_browser(db, settings.app_auth_secret,
                          body.context or request.cookies.get(COOKIE_NAME), body.transfer)
    bind_personal(db, row, settings.app_auth_secret,
                  token=body.personal_token, source_context=body.source_context)
    if body.accepted and body.event != "init":
        record_browser_event(db, row, "browser_page" if body.event == "page" else "browser_action",
                             body.page_url, attribution=body.attribution, action=body.action)
    db.commit()
    browser_id = row.metadata_json["browser_id"]
    context = issue_context(settings.app_auth_secret, browser_id)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(COOKIE_NAME, context, max_age=int(RETENTION.total_seconds()),
                        secure=True, httponly=False, samesite="lax", path="/")
    return {"context": context, "transfer": issue_context(settings.app_auth_secret, browser_id, transfer=True)}
