from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.app_service import AppAccessError
from app.models import DqsState, MasterclassEvent


DQS_REVEAL_EVENT_KEY = "app:dqs:revealed"
DQS_REVEAL_EVENT_TYPE = "app_revealed_dqs"


def dqs_is_revealed(db: Session, user_id: uuid.UUID) -> bool:
    """Return whether DQS has reached its course checkpoint for this user.

    The current contract uses the guarded ``app_revealed_dqs`` event. A
    non-empty legacy state also remains valid so people who actually filled
    DQS before the checkpoint existed are not locked out. The client telemetry
    event ``dqs_opened`` is intentionally not authorization evidence.
    """
    event_id = db.scalar(
        select(MasterclassEvent.id)
        .where(
            MasterclassEvent.user_id == user_id,
            MasterclassEvent.event_type == DQS_REVEAL_EVENT_TYPE,
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


def require_dqs_revealed(db: Session, user_id: uuid.UUID) -> None:
    if not dqs_is_revealed(db, user_id):
        raise AppAccessError(
            "DQS куплен, но откроется в четвёртом дне Мастер-класса"
        )
