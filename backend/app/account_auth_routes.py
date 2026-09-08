from __future__ import annotations

import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access_routes import account_payload
from app.account_onboarding_service import (
    account_onboarding_configuration_error,
    ensure_free_account_onboarding,
)
from app.account_security import token_hash, verify_password
from app.app_service import EMAIL_RE, normalize_email
from app.config import Settings, get_settings
from app.database import get_db
from app.legal_service import accept_current_legal_documents
from app.models import AccountCredential, AccountSession, User, UserEmail


router = APIRouter(tags=["account-auth"])
STATIC_DIR = Path(__file__).resolve().parent / "static"
COOKIE_NAME = "edabalans_account_session"
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60
MAX_REGISTRATION_ATTEMPTS = 5
_attempt_lock = threading.Lock()
_attempts: dict[str, tuple[int, float]] = {}
_registration_attempts: dict[str, tuple[int, float]] = {}


class PasswordLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)


class EmailRegistrationIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class NativeLegalIn(BaseModel):
    document_codes: list[str] = Field(min_length=2, max_length=2)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _attempt_key(request: Request, email: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}|{email}"


def _check_attempts(key: str) -> None:
    now = time.monotonic()
    with _attempt_lock:
        count, expires = _attempts.get(key, (0, now + LOGIN_WINDOW_SECONDS))
        if expires <= now:
            _attempts.pop(key, None)
            return
        if count >= MAX_LOGIN_ATTEMPTS:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Слишком много попыток. Попробуйте снова через 15 минут.",
            )


def _record_attempt(key: str, *, success: bool) -> None:
    with _attempt_lock:
        if success:
            _attempts.pop(key, None)
            return
        count, expires = _attempts.get(
            key, (0, time.monotonic() + LOGIN_WINDOW_SECONDS)
        )
        _attempts[key] = (count + 1, expires)


def _registration_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_registration_attempts(key: str) -> None:
    now = time.monotonic()
    with _attempt_lock:
        count, expires = _registration_attempts.get(key, (0, now + LOGIN_WINDOW_SECONDS))
        if expires <= now:
            _registration_attempts.pop(key, None)
            return
        if count >= MAX_REGISTRATION_ATTEMPTS:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Слишком много попыток. Попробуйте снова через 15 минут.",
            )


def _record_registration_attempt(key: str) -> None:
    with _attempt_lock:
        count, expires = _registration_attempts.get(
            key, (0, time.monotonic() + LOGIN_WINDOW_SECONDS)
        )
        _registration_attempts[key] = (count + 1, expires)


def native_session_user(request: Request, db: Session) -> User | None:
    raw_token = request.cookies.get(COOKIE_NAME, "")
    if not raw_token:
        return None
    now = datetime.now(UTC)
    row = db.scalar(
        select(AccountSession).where(
            AccountSession.token_hash == token_hash(raw_token),
            AccountSession.revoked_at.is_(None),
            AccountSession.expires_at > now,
        )
    )
    if row is None:
        return None
    credential = db.get(AccountCredential, row.user_id)
    user = db.get(User, row.user_id)
    if (
        credential is None
        or user is None
        or user.status != "active"
        or user.merged_into_user_id is not None
        or credential.password_version != row.password_version
    ):
        return None
    if row.last_seen_at is None or now - _aware(row.last_seen_at) >= timedelta(hours=1):
        row.last_seen_at = now
        db.commit()
    return user


def require_native_user(request: Request, db: Session) -> User:
    user = native_session_user(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход в личный кабинет")
    return user


def primary_email(db: Session, user_id) -> str:
    return db.scalar(
        select(UserEmail.email_normalized)
        .where(UserEmail.user_id == user_id)
        .order_by(UserEmail.is_primary.desc(), UserEmail.created_at)
        .limit(1)
    ) or ""


@router.get("/lk", include_in_schema=False)
@router.get("/lk/", include_in_schema=False)
def account_portal() -> FileResponse:
    response = FileResponse(STATIC_DIR / "account-portal.html")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.post("/api/account-auth/register")
def register_account(
    body: EmailRegistrationIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Create a no-access account and queue the existing email-to-messenger flow."""
    key = _registration_key(request)
    _check_registration_attempts(key)
    email = normalize_email(body.email)
    if not EMAIL_RE.match(email):
        _record_registration_attempt(key)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Введите корректный email")
    if not settings.account_onboarding_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Регистрация временно недоступна. Попробуйте немного позже.",
        )
    configuration_error = account_onboarding_configuration_error(settings)
    if configuration_error is not None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Регистрация временно недоступна. Попробуйте немного позже.",
        )
    try:
        _record_registration_attempt(key)
        ensure_free_account_onboarding(db, body.email, settings)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except IntegrityError:
        # Two identical first registrations can race before either email row
        # exists. The other transaction has created the same safe empty account.
        db.rollback()
    # The same message for an existing address avoids disclosing who already has an account.
    return {
        "ok": True,
        "message": "Проверьте почту: письмо со следующим шагом придёт в течение нескольких минут. Если его нет, загляните в «Спам».",
    }


@router.post("/api/account-auth/login")
def password_login(
    body: PasswordLoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    email = normalize_email(body.email)
    key = _attempt_key(request, email)
    _check_attempts(key)
    match = db.execute(
        select(User, AccountCredential)
        .join(UserEmail, UserEmail.user_id == User.id)
        .join(AccountCredential, AccountCredential.user_id == User.id)
        .where(UserEmail.email_normalized == email)
    ).first()
    valid = bool(
        match
        and match.User.status == "active"
        and match.User.merged_into_user_id is None
        and verify_password(
            body.password,
            match.AccountCredential.password_hash,
            settings.app_auth_secret,
        )
    )
    _record_attempt(key, success=valid)
    if not valid:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Неверный email или пароль",
        )
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=settings.account_session_days)
    db.add(
        AccountSession(
            user_id=match.User.id,
            token_hash=token_hash(raw_token),
            password_version=match.AccountCredential.password_version,
            expires_at=expires_at,
            last_seen_at=now,
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        raw_token,
        max_age=settings.account_session_days * 24 * 60 * 60,
        expires=expires_at,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return {"ok": True, "email": email, "expires_at": expires_at.isoformat()}


@router.get("/api/account-auth/session")
def account_session(request: Request, db: Session = Depends(get_db)) -> dict:
    user = native_session_user(request, db)
    return {
        "ok": True,
        "authenticated": user is not None,
        "email": primary_email(db, user.id) if user else "",
    }


@router.post("/api/account-auth/logout")
def account_logout(
    request: Request, response: Response, db: Session = Depends(get_db)
) -> dict:
    raw_token = request.cookies.get(COOKIE_NAME, "")
    if raw_token:
        db.execute(
            update(AccountSession)
            .where(
                AccountSession.token_hash == token_hash(raw_token),
                AccountSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
    return {"ok": True}


@router.get("/api/account-auth/account")
def native_account(request: Request, db: Session = Depends(get_db)) -> dict:
    user = require_native_user(request, db)
    return account_payload(primary_email(db, user.id), db)


@router.post("/api/account-auth/legal-acceptances")
def native_legal_acceptances(
    body: NativeLegalIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = require_native_user(request, db)
    accept_current_legal_documents(db, user.id, body.document_codes, source="native_account")
    db.commit()
    return account_payload(primary_email(db, user.id), db)
