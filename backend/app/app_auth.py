from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.app_service import AppAccessError, normalize_email, resolve_user_for_resource
from app.auth import session_admin
from app.config import Settings, get_settings
from app.database import get_db
from app.models import User


router = APIRouter(prefix="/api/app-auth", tags=["application-auth"])
CHALLENGE_SECONDS = 10 * 60
SESSION_SECONDS = 30 * 24 * 60 * 60
PLACEMENT_TOKEN_SECONDS = 10 * 365 * 24 * 60 * 60
RESEND_SECONDS = 60
_rate_lock = threading.Lock()
_last_challenge: dict[str, float] = {}
_challenge_attempts: dict[str, tuple[int, float]] = {}
MAX_CODE_ATTEMPTS = 5


class ChallengeIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class VerifyIn(BaseModel):
    challenge_token: str = Field(min_length=20, max_length=4096)
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


def _secret(settings: Settings) -> bytes:
    if not settings.app_auth_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "application login is not configured")
    return settings.app_auth_secret.encode("utf-8")


def _encode(payload: dict[str, Any], settings: Settings) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(_secret(settings), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _decode(token: str, settings: Settings, expected_kind: str) -> dict[str, Any]:
    try:
        body, signature = token.rsplit(".", 1)
        expected = hmac.new(_secret(settings), body.encode("ascii"), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(
            base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8")
        )
        if payload.get("kind") != expected_kind or int(payload.get("expires", 0)) < int(time.time()):
            raise ValueError("expired")
        return payload
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login token is invalid or expired") from exc


def send_login_code(email: str, code: str, settings: Settings) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "email delivery is not configured")
    message = EmailMessage()
    message["Subject"] = "Код входа в ЕдаБаланс"
    message["From"] = settings.smtp_from_email
    message["To"] = email
    message.set_content(
        "Код входа в приложение ЕдаБаланс: "
        f"{code}\n\nОн действует 10 минут. Если вы не запрашивали код, ничего делать не нужно."
    )
    context = ssl.create_default_context()
    try:
        if settings.smtp_use_ssl:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=15, context=context
            )
        else:
            smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
        with smtp:
            if not settings.smtp_use_ssl and settings.smtp_starttls:
                smtp.starttls(context=context)
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "email delivery is temporarily unavailable") from exc


def create_challenge(email: str, code: str, settings: Settings) -> str:
    expires = int(time.time()) + CHALLENGE_SECONDS
    nonce = secrets.token_hex(16)
    code_digest = hmac.new(
        _secret(settings), f"{email}|{code}|{expires}|{nonce}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return _encode(
        {
            "kind": "email_challenge",
            "email": email,
            "expires": expires,
            "nonce": nonce,
            "code_digest": code_digest,
        },
        settings,
    )


def _challenge_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def register_challenge(token: str) -> None:
    now = time.time()
    with _rate_lock:
        expired = [key for key, (_, expires) in _challenge_attempts.items() if expires < now]
        for key in expired:
            _challenge_attempts.pop(key, None)
        _challenge_attempts[_challenge_key(token)] = (0, now + CHALLENGE_SECONDS)


def check_challenge_attempts(token: str) -> None:
    with _rate_lock:
        attempts, _ = _challenge_attempts.get(
            _challenge_key(token), (0, time.time() + CHALLENGE_SECONDS)
        )
    if attempts >= MAX_CODE_ATTEMPTS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many code attempts; request a new code",
        )


def record_challenge_attempt(token: str, *, consumed: bool = False) -> None:
    key = _challenge_key(token)
    with _rate_lock:
        attempts, expires = _challenge_attempts.get(
            key, (0, time.time() + CHALLENGE_SECONDS)
        )
        _challenge_attempts[key] = (
            MAX_CODE_ATTEMPTS if consumed else attempts + 1,
            expires,
        )


def verify_challenge(token: str, code: str, settings: Settings) -> str:
    payload = _decode(token, settings, "email_challenge")
    expected = hmac.new(
        _secret(settings),
        f"{payload['email']}|{code}|{payload['expires']}|{payload['nonce']}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not secrets.compare_digest(expected, str(payload.get("code_digest", ""))):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "verification code is incorrect")
    return str(payload["email"])


def create_app_session(email: str, settings: Settings) -> str:
    return _encode(
        {
            "kind": "app_session",
            "email": email,
            "expires": int(time.time()) + SESSION_SECONDS,
            "nonce": secrets.token_hex(16),
        },
        settings,
    )


def create_placement_token(placement: str, settings: Settings) -> str:
    return _encode(
        {
            "kind": "masterclass_placement",
            "placement": placement,
            "expires": int(time.time()) + PLACEMENT_TOKEN_SECONDS,
        },
        settings,
    )


def require_placement(
    request: Request,
    placement: str,
    placement_token: str,
    settings: Settings,
) -> None:
    if session_admin(request):
        return
    payload = _decode(placement_token, settings, "masterclass_placement")
    actual = str(payload.get("placement", ""))
    if not secrets.compare_digest(actual, placement):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this masterclass step is not available here")


def session_email(request: Request, settings: Settings) -> str | None:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    payload = _decode(authorization[7:].strip(), settings, "app_session")
    return normalize_email(str(payload.get("email", "")))


def require_app_user(
    request: Request,
    requested_email: str,
    db: Session,
    resource_code: str,
    settings: Settings,
) -> User:
    email = normalize_email(requested_email)
    if session_admin(request):
        authenticated_email = email
    else:
        authenticated_email = session_email(request, settings)
        if not authenticated_email or not secrets.compare_digest(authenticated_email, email):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "email confirmation is required")
    try:
        return resolve_user_for_resource(db, authenticated_email, resource_code)
    except AppAccessError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc


@router.post("/challenge")
def request_challenge(
    body: ChallengeIn,
    request: Request,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    email = normalize_email(body.email)
    if not email or "@" not in email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "email is invalid")
    rate_key = f"{request.client.host if request.client else 'unknown'}|{email}"
    now = time.monotonic()
    with _rate_lock:
        last = _last_challenge.get(rate_key)
        if last is not None and now - last < RESEND_SECONDS:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "code was already sent; try again in a minute")
        _last_challenge[rate_key] = now

    try:
        resolve_user_for_resource(
            db,
            email,
            "ACCESS_MASTERCLASS",
            require_legal_acceptance=False,
        )
    except AppAccessError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge_token = create_challenge(email, code, settings)
    register_challenge(challenge_token)
    send_login_code(email, code, settings)
    return {
        "ok": True,
        "challenge_token": challenge_token,
        "expires_in": CHALLENGE_SECONDS,
        "resend_in": RESEND_SECONDS,
    }


@router.post("/verify")
def verify_code(
    body: VerifyIn,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    check_challenge_attempts(body.challenge_token)
    try:
        email = verify_challenge(body.challenge_token, body.code, settings)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            record_challenge_attempt(body.challenge_token)
        raise
    record_challenge_attempt(body.challenge_token, consumed=True)
    try:
        resolve_user_for_resource(
            db,
            email,
            "ACCESS_MASTERCLASS",
            require_legal_acceptance=False,
        )
    except AppAccessError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return {
        "ok": True,
        "email": email,
        "session_token": create_app_session(email, settings),
        "expires_in": SESSION_SECONDS,
    }
