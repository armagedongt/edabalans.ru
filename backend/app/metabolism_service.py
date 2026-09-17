from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.app_service import AppAccessError, require_user_resource
from app.models import CourseStageProgress, User


def metabolism_stage_complete(db: Session, user_id: uuid.UUID) -> bool:
    return db.scalar(select(CourseStageProgress.id).where(
        CourseStageProgress.user_id == user_id,
        CourseStageProgress.course_code == "calories",
        CourseStageProgress.stage_number == 2,
        CourseStageProgress.completed_at.is_not(None),
    )) is not None


def require_metabolism_user(db: Session, user: User) -> User:
    require_user_resource(db, user, "ACCESS_CALORIES")
    if not metabolism_stage_complete(db, user.id):
        raise AppAccessError("Калькулятор откроется после второго этапа Калорийного курса")
    return user
