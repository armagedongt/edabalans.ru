from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    PersonalAccessLink,
    Resource,
    User,
    UserAccess,
    UserCoursePolicy,
    UserEmail,
)


BLOCKING_REVIEW_STATUSES = {"waiting_registration", "pending", "conflict"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalized_email(value: str | None) -> str:
    return (value or "").strip().lower()


def user_for_email(db: Session, email: str | None) -> User | None:
    normalized = normalized_email(email)
    if not EMAIL_RE.match(normalized):
        return None
    return db.scalar(
        select(User)
        .join(UserEmail, UserEmail.user_id == User.id)
        .where(
            UserEmail.email_normalized == normalized,
            User.status == "active",
            User.merged_into_user_id.is_(None),
        )
    )


def review_blocks_access(user: User) -> bool:
    return user.access_review_status in BLOCKING_REVIEW_STATUSES


def create_link_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


def link_by_token(
    db: Session, token: str, *, for_update: bool = False
) -> PersonalAccessLink | None:
    if not token or len(token) > 256:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    statement = select(PersonalAccessLink).where(PersonalAccessLink.token_hash == digest)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def active_link(link: PersonalAccessLink, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    expires_at = link.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if link.status != "active":
        return False
    return not expires_at or expires_at > now


def resources_for_codes(db: Session, codes: list[str]) -> dict[str, Resource]:
    unique = list(dict.fromkeys(codes))
    if not unique:
        return {}
    resources = {
        item.code: item
        for item in db.scalars(
            select(Resource).where(Resource.code.in_(unique), Resource.status == "active")
        )
    }
    if set(unique) != set(resources):
        missing = sorted(set(unique) - set(resources))
        raise ValueError(f"unknown resources: {', '.join(missing)}")
    return resources


def grant_resources(
    db: Session,
    user: User,
    resource_codes: list[str],
    *,
    source: str,
    source_payment_id: uuid.UUID | None = None,
    unlock_modes: dict[str, str] | None = None,
) -> list[str]:
    resources = resources_for_codes(db, resource_codes)
    now = datetime.now(timezone.utc)
    granted: list[str] = []
    for code, resource in resources.items():
        current = db.scalar(
            select(UserAccess).where(
                UserAccess.user_id == user.id,
                UserAccess.resource_id == resource.id,
                UserAccess.revoked_at.is_(None),
                (UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now)),
            )
        )
        if current is None:
            db.add(
                UserAccess(
                    user_id=user.id,
                    resource_id=resource.id,
                    source_payment_id=source_payment_id,
                    source=source,
                    granted_at=now,
                )
            )
            granted.append(code)
        mode = (unlock_modes or {}).get(code, "paced")
        if mode not in {"paced", "fully_unlocked"}:
            raise ValueError(f"invalid unlock mode for {code}")
        policy = db.scalar(
            select(UserCoursePolicy).where(
                UserCoursePolicy.user_id == user.id,
                UserCoursePolicy.resource_id == resource.id,
            )
        )
        if policy is None:
            db.add(
                UserCoursePolicy(
                    user_id=user.id,
                    resource_id=resource.id,
                    unlock_mode=mode,
                    source=source,
                )
            )
        elif mode == "fully_unlocked":
            policy.unlock_mode = mode
            policy.source = source
    return granted


def complete_review(user: User, note: str) -> None:
    user.access_review_status = "completed"
    user.access_review_note = note
    user.access_reviewed_at = datetime.now(timezone.utc)
    user.tilda_access_status = "granted"


def amount_number(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value == value.to_integral() else float(value)
