from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MasterclassEvent, Resource, UserAccess, UserCoursePolicy


COURSE_RESOURCE_CODES = frozenset(
    {
        "ACCESS_MASTERCLASS",
        "ACCESS_RECIPES",
        "ACCESS_CALORIES",
        "ACCESS_STRENGTH",
    }
)
MASTERCLASS_PREREQUISITE_RESOURCES = frozenset(
    {"ACCESS_CALORIES", "ACCESS_STRENGTH"}
)


def active_resource_codes(db: Session, user_id: uuid.UUID) -> set[str]:
    now = datetime.now(timezone.utc)
    return set(
        db.scalars(
            select(Resource.code)
            .join(UserAccess, UserAccess.resource_id == Resource.id)
            .where(
                UserAccess.user_id == user_id,
                UserAccess.revoked_at.is_(None),
                UserAccess.paused_at.is_(None),
                UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now),
                Resource.status == "active",
            )
        )
    )


def course_unlock_mode(db: Session, user_id: uuid.UUID, resource_code: str) -> str:
    mode = db.scalar(
        select(UserCoursePolicy.unlock_mode)
        .join(Resource, Resource.id == UserCoursePolicy.resource_id)
        .where(
            UserCoursePolicy.user_id == user_id,
            Resource.code == resource_code,
        )
    )
    return str(mode or "paced")


def course_fully_unlocked(db: Session, user_id: uuid.UUID, resource_code: str) -> bool:
    return course_unlock_mode(db, user_id, resource_code) == "fully_unlocked"


def masterclass_completed(db: Session, user_id: uuid.UUID) -> bool:
    return db.scalar(
        select(MasterclassEvent.id).where(
            MasterclassEvent.user_id == user_id,
            MasterclassEvent.event_type == "masterclass_completed",
        )
    ) is not None


def course_entry_unlocked(db: Session, user_id: uuid.UUID, resource_code: str) -> bool:
    if course_fully_unlocked(db, user_id, resource_code):
        return True
    if resource_code in MASTERCLASS_PREREQUISITE_RESOURCES:
        return masterclass_completed(db, user_id)
    return True


def set_course_unlock_mode(
    db: Session,
    user_id: uuid.UUID,
    resource_code: str,
    unlock_mode: str,
    *,
    source: str,
) -> tuple[bool, str]:
    if resource_code not in COURSE_RESOURCE_CODES:
        return False, "resource_is_not_a_course"
    if unlock_mode not in {"paced", "fully_unlocked"}:
        return False, "invalid_unlock_mode"
    resource = db.scalar(
        select(Resource).where(
            Resource.code == resource_code,
            Resource.status == "active",
        )
    )
    if resource is None:
        return False, "resource_not_found"
    if resource_code not in active_resource_codes(db, user_id):
        return False, "active_access_required"
    policy = db.scalar(
        select(UserCoursePolicy).where(
            UserCoursePolicy.user_id == user_id,
            UserCoursePolicy.resource_id == resource.id,
        )
    )
    if policy is None:
        policy = UserCoursePolicy(
            user_id=user_id,
            resource_id=resource.id,
            unlock_mode=unlock_mode,
            source=source,
        )
        db.add(policy)
    else:
        policy.unlock_mode = unlock_mode
        policy.source = source
    return True, unlock_mode
