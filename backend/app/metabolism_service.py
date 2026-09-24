from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.app_service import AppAccessError, require_user_resource
from app.course_access_service import course_entry_unlocked
from app.models import User


def metabolism_is_unlocked(db: Session, user_id: uuid.UUID) -> bool:
    return course_entry_unlocked(db, user_id, "ACCESS_CALORIES")


def require_metabolism_user(db: Session, user: User) -> User:
    require_user_resource(db, user, "ACCESS_CALORIES")
    if not metabolism_is_unlocked(db, user.id):
        raise AppAccessError("Калькулятор откроется после завершения Мастер-класса")
    return user
