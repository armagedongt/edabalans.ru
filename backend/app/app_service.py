from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Resource, User, UserAccess, UserEmail
from app.access_service import review_blocks_access
from app.legal_service import legal_acceptances_complete


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
EXTRA_ACCESS_SOURCE = "temporary_extra_all_apps"


class AppAccessError(ValueError):
    pass


def normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def resolve_user_for_resource(
    db: Session,
    email: str | None,
    resource_code: str,
    *,
    require_legal_acceptance: bool = True,
) -> User:
    normalized = normalize_email(email)
    if not EMAIL_RE.match(normalized):
        raise AppAccessError("Введите корректный email")

    user = db.scalar(
        select(User)
        .join(UserEmail, UserEmail.user_id == User.id)
        .where(
            UserEmail.email_normalized == normalized,
            User.status == "active",
            User.merged_into_user_id.is_(None),
        )
    )
    if not user:
        raise AppAccessError("Этот email не найден в списке доступа")

    if review_blocks_access(user):
        raise AppAccessError(
            "Исторические покупки требуют подтверждения Сергея. Напишите Сергею, чтобы он проверил и открыл нужные программы."
        )

    if require_legal_acceptance and not legal_acceptances_complete(db, user.id):
        raise AppAccessError(
            "Сначала примите дисклеймер и политику обработки данных в личном кабинете"
        )

    now = datetime.now(timezone.utc)
    access_filters = (
        UserAccess.user_id == user.id,
        Resource.code == resource_code,
        Resource.status == "active",
        UserAccess.revoked_at.is_(None),
        (UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now)),
    )
    access = db.scalar(
        select(UserAccess)
        .join(Resource, Resource.id == UserAccess.resource_id)
        .where(
            *access_filters,
            UserAccess.source != EXTRA_ACCESS_SOURCE,
        )
        .limit(1)
    )
    if not access:
        access = db.scalar(
            select(UserAccess)
            .join(Resource, Resource.id == UserAccess.resource_id)
            .where(
                *access_filters,
                UserAccess.source == EXTRA_ACCESS_SOURCE,
            )
            .limit(1)
        )
    if not access:
        raise AppAccessError("Для этого email нет доступа к приложению")
    return user


def primary_email(db: Session, user_id: uuid.UUID) -> str:
    email = db.scalar(
        select(UserEmail.email_normalized)
        .where(UserEmail.user_id == user_id)
        .order_by(UserEmail.is_primary.desc(), UserEmail.created_at.asc())
        .limit(1)
    )
    return email or ""


def utc_iso(value: datetime | None) -> str:
    return value.astimezone(timezone.utc).isoformat() if value else ""


def clean_json(value: Any, fallback: Any) -> Any:
    return value if isinstance(value, type(fallback)) else fallback
