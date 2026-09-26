from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access_service import course_start_is_open
from app.course_access_service import active_resource_codes, course_entry_unlocked
from app.models import (
    AdminAppEdit,
    DqsState,
    MasterclassEvent,
    Resource,
    User,
    UserAccess,
    UserApplicationPolicy,
)


APP_CODES = ("dqs", "strength", "metabolism")
APP_RESOURCES: dict[str, tuple[str, ...]] = {
    "dqs": ("dqs",),
    "strength": ("strength", "ACCESS_STRENGTH"),
    "metabolism": ("metabolism", "ACCESS_CALORIES"),
}


def _dqs_reached_course_checkpoint(db: Session, user_id: uuid.UUID) -> bool:
    event_id = db.scalar(
        select(MasterclassEvent.id)
        .where(
            MasterclassEvent.user_id == user_id,
            MasterclassEvent.event_type == "app_revealed_dqs",
        )
        .limit(1)
    )
    if event_id is not None:
        return True
    state = db.scalar(select(DqsState).where(DqsState.user_id == user_id))
    return bool(
        state
        and state.source != "admin_open"
        and (state.start_date or state.days)
    )


def application_access_state(db: Session, user_id: uuid.UUID, app_code: str) -> dict[str, bool | str]:
    """Resolve one application's right and start gate from canonical facts."""
    if app_code not in APP_CODES:
        raise ValueError("unknown_application")
    access_codes = active_resource_codes(db, user_id)
    entitled = bool(access_codes.intersection(APP_RESOURCES[app_code]))
    policy = db.scalar(
        select(UserApplicationPolicy).where(
            UserApplicationPolicy.user_id == user_id,
            UserApplicationPolicy.app_code == app_code,
        )
    )
    manual_start_open = bool(policy and policy.start_mode == "open")
    if app_code == "dqs":
        automatic_start_open = _dqs_reached_course_checkpoint(db, user_id)
    elif app_code == "strength":
        automatic_start_open = (
            "strength" in access_codes
            or course_start_is_open(db, user_id, "ACCESS_STRENGTH")
        )
    else:
        automatic_start_open = (
            "metabolism" in access_codes
            or course_entry_unlocked(db, user_id, "ACCESS_CALORIES")
        )
    return {
        "entitled": entitled,
        "start_open": entitled and (manual_start_open or automatic_start_open),
        "manual_start_open": manual_start_open,
    }


def set_manual_application_start(
    db: Session,
    user_id: uuid.UUID,
    app_code: str,
    *,
    start_open: bool,
    admin: str,
) -> dict[str, bool | str]:
    """Set the reversible immediate-start override without withdrawing a right."""
    if app_code not in APP_CODES:
        raise ValueError("unknown_application")
    user = db.get(User, user_id)
    if user is None or user.merged_into_user_id is not None:
        raise ValueError("user_not_found")
    current = application_access_state(db, user_id, app_code)
    now = datetime.now(timezone.utc)
    if start_open and not current["entitled"]:
        resource = db.scalar(
            select(Resource).where(Resource.code == app_code, Resource.status == "active")
        )
        if resource is None:
            raise ValueError("application_resource_not_found")
        manual_row = db.scalar(
            select(UserAccess).where(
                UserAccess.user_id == user_id,
                UserAccess.resource_id == resource.id,
                UserAccess.source_payment_id.is_(None),
            )
        )
        if manual_row is None:
            db.add(UserAccess(
                user_id=user_id,
                resource_id=resource.id,
                source_payment_id=None,
                source="manual_admin",
                granted_at=now,
            ))
        else:
            manual_row.revoked_at = None
            manual_row.paused_at = None
            manual_row.expires_at = None
    policy = db.scalar(
        select(UserApplicationPolicy).where(
            UserApplicationPolicy.user_id == user_id,
            UserApplicationPolicy.app_code == app_code,
        )
    )
    if policy is None:
        policy = UserApplicationPolicy(
            user_id=user_id,
            app_code=app_code,
            start_mode="open" if start_open else "auto",
            source="manual_admin",
        )
        db.add(policy)
    else:
        policy.start_mode = "open" if start_open else "auto"
        policy.source = "manual_admin"
    db.add(AdminAppEdit(
        admin_username=admin,
        target_user_id=user_id,
        app_code="crm",
        action="set_application_start",
        details={"app_code": app_code, "start_open": start_open},
    ))
    db.commit()
    return application_access_state(db, user_id, app_code)
