from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.app_service import AppAccessError, require_user_resource
from app.application_access_service import application_access_state
from app.models import User


def metabolism_is_unlocked(db: Session, user_id: uuid.UUID) -> bool:
    return bool(application_access_state(db, user_id, "metabolism")["start_open"])


def require_metabolism_user(db: Session, user: User) -> User:
    require_user_resource(db, user, ("metabolism", "ACCESS_CALORIES"))
    if not metabolism_is_unlocked(db, user.id):
        raise AppAccessError("Калькулятор откроется после нужного этапа курса")
    return user
