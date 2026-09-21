from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.account_auth_routes import COOKIE_NAME
from app.account_security import token_hash
from app.access_service import user_for_email
from app.config import Settings
from app.models import (
    AccountCredential,
    AccountSession,
    Payment,
    PaymentBrowserGrant,
)


GRANT_COOKIE_NAME = "edabalans_payment_grant"
CHECKOUT_GRANT_LIFETIME = timedelta(hours=3)


def create_payment_browser_grant(
    db: Session,
    payment: Payment,
    email: str,
    settings: Settings,
) -> str | None:
    """Bind a pending first credential issue to the browser starting checkout."""
    user = user_for_email(db, email)
    if user is not None and db.get(AccountCredential, user.id) is not None:
        return None
    existing = db.scalar(
        select(PaymentBrowserGrant).where(PaymentBrowserGrant.payment_id == payment.id)
    )
    if existing is not None:
        return None
    raw = secrets.token_urlsafe(32)
    db.add(
        PaymentBrowserGrant(
            payment_id=payment.id,
            token_hash=token_hash(raw),
            expires_at=datetime.now(UTC) + CHECKOUT_GRANT_LIFETIME,
        )
    )
    db.commit()
    return raw


def set_payment_grant_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        GRANT_COOKIE_NAME,
        raw_token,
        max_age=int(CHECKOUT_GRANT_LIFETIME.total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def browser_grant(
    db: Session, request: Request, payment: Payment, *, for_update: bool = False
) -> tuple[PaymentBrowserGrant, str] | None:
    raw = request.cookies.get(GRANT_COOKIE_NAME, "")
    if not raw:
        return None
    query = select(PaymentBrowserGrant).where(
        PaymentBrowserGrant.payment_id == payment.id,
        PaymentBrowserGrant.token_hash == token_hash(raw),
    )
    if for_update:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None or _aware(row.expires_at) <= datetime.now(UTC):
        return None
    return row, raw


def auto_login_state(
    db: Session, request: Request, payment: Payment, settings: Settings
) -> str:
    if payment.payment_status != "paid":
        return "waiting"
    grant_exists = db.scalar(
        select(PaymentBrowserGrant.id).where(PaymentBrowserGrant.payment_id == payment.id)
    ) is not None
    if not grant_exists:
        return "existing_account"
    match = browser_grant(db, request, payment)
    if match is None:
        return "email_login"
    if payment.paid_at is None:
        return "waiting"
    deadline = _aware(payment.paid_at) + timedelta(minutes=settings.payment_browser_grant_minutes)
    if datetime.now(UTC) >= deadline:
        return "expired"
    if payment.user_id is None or db.get(AccountCredential, payment.user_id) is None:
        return "waiting_credentials"
    return "auto_login"


def _session_token(raw_grant: str, payment: Payment, settings: Settings) -> str:
    if not settings.app_auth_secret:
        raise RuntimeError("APP_AUTH_SECRET is required")
    message = f"purchase-session-v1\0{raw_grant}\0{payment.id}\0{payment.user_id}".encode()
    digest = hmac.new(settings.app_auth_secret.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def claim_payment_session(
    db: Session,
    request: Request,
    response: Response,
    payment: Payment,
    settings: Settings,
) -> datetime:
    if payment.payment_status != "paid" or payment.user_id is None or payment.paid_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Оплата ещё не подтверждена")
    now = datetime.now(UTC)
    current_session_token = request.cookies.get(COOKIE_NAME, "")
    if current_session_token:
        current_session = db.scalar(
            select(AccountSession).where(
                AccountSession.token_hash == token_hash(current_session_token),
                AccountSession.user_id == payment.user_id,
                AccountSession.revoked_at.is_(None),
                AccountSession.expires_at > now,
            )
        )
        credential = db.get(AccountCredential, payment.user_id)
        if (
            current_session is not None
            and credential is not None
            and current_session.password_version == credential.password_version
        ):
            return _aware(current_session.expires_at)
    match = browser_grant(db, request, payment, for_update=True)
    if match is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Эта кнопка доступна только в браузере оплаты")
    grant, raw_grant = match
    deadline = _aware(payment.paid_at) + timedelta(minutes=settings.payment_browser_grant_minutes)
    if now >= deadline:
        raise HTTPException(status.HTTP_410_GONE, "Срок быстрого входа истёк. Используйте письмо с доступом")
    credential = db.get(AccountCredential, payment.user_id)
    if credential is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Данные для входа ещё создаются")
    raw_session = _session_token(raw_grant, payment, settings)
    session = db.scalar(
        select(AccountSession).where(AccountSession.browser_grant_id == grant.id)
    )
    expires_at = now + timedelta(days=settings.account_session_days)
    if session is None:
        session = AccountSession(
            user_id=payment.user_id,
            token_hash=token_hash(raw_session),
            browser_grant_id=grant.id,
            password_version=credential.password_version,
            expires_at=expires_at,
            last_seen_at=now,
        )
        db.add(session)
    else:
        expires_at = _aware(session.expires_at)
    if grant.consumed_at is None:
        grant.consumed_at = now
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        raw_session,
        max_age=max(0, int((expires_at - now).total_seconds())),
        expires=expires_at,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(GRANT_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
    return expires_at
