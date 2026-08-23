from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Contact, Sequence, SequenceRun, SequenceVersion
from app.seed import PREPURCHASE_CODE, START_ENTRY_CODE, WELCOME_CODE


ACTIVE_RUN_STATUSES = ("active", "waiting")
PRESALE_SEQUENCE_CODES = (START_ENTRY_CODE, WELCOME_CODE, PREPURCHASE_CODE)


def stop_presale_runs_for_user(
    session: Session,
    user_id: str,
    *,
    reason: str = "masterclass_owned",
) -> int:
    """Stop every presale run for one CRM identity, across all linked contacts."""
    runs = list(
        session.scalars(
            select(SequenceRun)
            .join(Contact, Contact.id == SequenceRun.contact_id)
            .join(SequenceVersion, SequenceVersion.id == SequenceRun.sequence_version_id)
            .join(Sequence, Sequence.id == SequenceVersion.sequence_id)
            .where(
                Contact.user_id == user_id,
                Sequence.code.in_(PRESALE_SEQUENCE_CODES),
                SequenceRun.status.in_(ACTIVE_RUN_STATUSES),
            )
        )
    )
    now = datetime.now(UTC)
    for run in runs:
        run.status = "completed"
        run.finished_at = now
        run.next_action_at = None
        run.context = {**(run.context or {}), "stopped_reason": reason}
    return len(runs)


def stop_presale_runs_from_purchase_events(session: Session) -> int:
    """Consume confirmed site purchase events at the lifecycle boundary."""
    user_ids = session.scalars(
        select(Contact.user_id)
        .join(SequenceRun, SequenceRun.contact_id == Contact.id)
        .join(SequenceVersion, SequenceVersion.id == SequenceRun.sequence_version_id)
        .join(Sequence, Sequence.id == SequenceVersion.sequence_id)
        .where(
            Contact.user_id.is_not(None),
            SequenceRun.status.in_(ACTIVE_RUN_STATUSES),
            Sequence.code.in_(PRESALE_SEQUENCE_CODES),
            text(
                "EXISTS (SELECT 1 FROM masterclass_events me "
                "WHERE CAST(me.user_id AS TEXT) = CAST(tg_contacts.user_id AS TEXT) "
                "AND me.event_type = 'masterclass_purchase_confirmed')"
            ),
        )
        .distinct()
    )
    return sum(
        stop_presale_runs_for_user(session, str(user_id), reason="masterclass_purchase_confirmed")
        for user_id in user_ids
    )


def reconcile_masterclass_presale_runs(session: Session) -> int:
    """Safety net: apply the lifecycle rule to every currently linked owner.

    Purchase/access is central CRM state.  The scheduler performs this one global
    reconciliation instead of embedding a purchase query before every message.
    """
    user_ids = session.scalars(
        select(Contact.user_id)
        .join(SequenceRun, SequenceRun.contact_id == Contact.id)
        .join(SequenceVersion, SequenceVersion.id == SequenceRun.sequence_version_id)
        .join(Sequence, Sequence.id == SequenceVersion.sequence_id)
        .where(
            Contact.user_id.is_not(None),
            SequenceRun.status.in_(ACTIVE_RUN_STATUSES),
            Sequence.code.in_(PRESALE_SEQUENCE_CODES),
            text(
                "EXISTS (SELECT 1 FROM user_accesses ua "
                "JOIN resources r ON r.id = ua.resource_id "
                "WHERE CAST(ua.user_id AS TEXT) = CAST(tg_contacts.user_id AS TEXT) "
                "AND r.code = 'ACCESS_MASTERCLASS' "
                "AND ua.revoked_at IS NULL "
                "AND (ua.expires_at IS NULL OR ua.expires_at > CURRENT_TIMESTAMP))"
            ),
        )
        .distinct()
    )
    return sum(
        stop_presale_runs_for_user(session, str(user_id), reason="masterclass_access_reconciled")
        for user_id in user_ids
    )
