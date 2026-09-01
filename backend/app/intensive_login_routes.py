from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import TelegramLoginAttempt, User

router = APIRouter(tags=["intensive-telegram-login"])
STATIC = Path(__file__).with_name("static") / "intensive-login"
ATTEMPT_COOKIE = "edabalans_tg_attempt"
SESSION_COOKIE = "edabalans_tg_session"
TTL_SECONDS = 15 * 60


class ConfirmCodeIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


def _sign(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _pack_cookie(secret: str, value: str) -> str:
    return f"{value}.{_sign(secret, value)}"


def _unpack_cookie(secret: str, value: str | None) -> str | None:
    if not secret or not value or "." not in value:
        return None
    raw, supplied = value.rsplit(".", 1)
    return raw if hmac.compare_digest(supplied, _sign(secret, raw)) else None


def _session_user_id(secret: str, value: str | None) -> str | None:
    raw = _unpack_cookie(secret, value)
    if raw is None or ":" not in raw:
        return None
    user_id, expires_raw = raw.rsplit(":", 1)
    try:
        if int(expires_raw) <= int(time.time()):
            return None
    except ValueError:
        return None
    return user_id


@router.get("/telegram-login", include_in_schema=False)
def page() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@router.get("/telegram-login/{asset}", include_in_schema=False)
def asset(asset: str) -> FileResponse:
    if asset not in {"app.js", "styles.css"}:
        raise HTTPException(404)
    return FileResponse(STATIC / asset)


@router.post("/api/intensive/telegram-login/start")
def start(response: Response, settings: Settings = Depends(get_settings)) -> dict:
    secret = settings.app_auth_secret
    username = settings.telegram_test_bot_username.strip().lstrip("@")
    if not secret or not username:
        raise HTTPException(503, "Telegram login is not configured")
    timestamp = int(time.time())
    nonce = secrets.token_bytes(16)
    head = struct.pack(">I16s", timestamp, nonce)
    mac = hmac.new(secret.encode(), b"I" + head, hashlib.sha256).digest()[:12]
    payload = "I" + base64.urlsafe_b64encode(head + mac).decode().rstrip("=")
    browser_value = base64.urlsafe_b64encode(nonce).decode().rstrip("=")
    response.set_cookie(ATTEMPT_COOKIE, _pack_cookie(secret, browser_value), max_age=TTL_SECONDS, secure=True, httponly=True, samesite="lax", path="/")
    return {"deep_link": f"https://t.me/{username}?start={payload}", "expires_in": TTL_SECONDS}


@router.get("/api/intensive/telegram-login/status")
def status(request: Request, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    session_user_id = _session_user_id(settings.app_auth_secret, request.cookies.get(SESSION_COOKIE))
    if session_user_id:
        try:
            parsed_user_id = uuid.UUID(session_user_id)
        except ValueError:
            parsed_user_id = None
        user = db.get(User, parsed_user_id) if parsed_user_id else None
        if user:
            return {"linked": True, "user": {"first_name": user.display_name, "username": None}}
    raw = _unpack_cookie(settings.app_auth_secret, request.cookies.get(ATTEMPT_COOKIE))
    if raw is None:
        return {"linked": False, "reason": "no_attempt"}
    try:
        nonce = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except ValueError:
        return {"linked": False, "reason": "invalid_attempt"}
    attempt = db.scalar(select(TelegramLoginAttempt).where(TelegramLoginAttempt.nonce_hash == hashlib.sha256(nonce).hexdigest()))
    if not attempt:
        return {"linked": False, "reason": "pending"}
    expires = attempt.expires_at.replace(tzinfo=attempt.expires_at.tzinfo or timezone.utc)
    if expires <= datetime.now(timezone.utc):
        return {"linked": False, "reason": "expired"}
    return {"linked": False, "reason": "code_required"}


@router.post("/api/intensive/telegram-login/confirm")
def confirm(body: ConfirmCodeIn, request: Request, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    raw = _unpack_cookie(settings.app_auth_secret, request.cookies.get(ATTEMPT_COOKIE))
    if raw is None:
        raise HTTPException(401, "login attempt is missing")
    try:
        nonce = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except ValueError as exc:
        raise HTTPException(401, "login attempt is invalid") from exc
    attempt = db.scalar(select(TelegramLoginAttempt).where(TelegramLoginAttempt.nonce_hash == hashlib.sha256(nonce).hexdigest()).with_for_update())
    if not attempt:
        raise HTTPException(409, "Telegram confirmation is pending")
    expires = attempt.expires_at.replace(tzinfo=attempt.expires_at.tzinfo or timezone.utc)
    if expires <= datetime.now(timezone.utc) or attempt.failed_attempts >= 5:
        raise HTTPException(410, "login attempt expired or locked")
    supplied_hash = hashlib.sha256(body.code.encode()).hexdigest()
    if not hmac.compare_digest(supplied_hash, attempt.verification_code_hash):
        attempt.failed_attempts += 1
        db.commit()
        raise HTTPException(422, "wrong confirmation code")
    attempt.verified_at = datetime.now(timezone.utc)
    db.commit()
    user = db.get(User, attempt.user_id)
    session_value = f"{attempt.user_id}:{int(time.time()) + 86400}"
    response.set_cookie(SESSION_COOKIE, _pack_cookie(settings.app_auth_secret, session_value), max_age=86400, secure=True, httponly=True, samesite="lax", path="/")
    response.delete_cookie(ATTEMPT_COOKIE, path="/")
    return {"linked": True, "user": {"first_name": attempt.first_name or (user.display_name if user else None), "username": attempt.username}}


@router.post("/api/intensive/telegram-login/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(ATTEMPT_COOKIE, path="/")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
