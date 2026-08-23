from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Callable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Contact, ContentItem, ManualMessage, MasterclassNotification


DIGITAL_ACCESS_CODES = {
    "ACCESS_RECIPES",
    "ACCESS_CALORIES",
    "ACCESS_STRENGTH",
    "ACCESS_CONSULTATION_RECORDINGS",
}


def crm_access_codes(session: Session, user_id: str) -> set[str]:
    rows = session.execute(
        text(
            "SELECT r.code FROM user_accesses ua "
            "JOIN resources r ON r.id = ua.resource_id "
            "WHERE ua.user_id = :user_id AND ua.revoked_at IS NULL "
            "AND (ua.expires_at IS NULL OR ua.expires_at > CURRENT_TIMESTAMP)"
        ),
        {"user_id": user_id},
    )
    return {str(row[0]) for row in rows}


def content_code_for(notification: MasterclassNotification, access: set[str]) -> str | None:
    if notification.notification_kind == "owner_closing_review":
        return None
    if notification.notification_kind == "recipes_followup":
        if "ACCESS_RECIPES" not in access:
            return "tpl_postpurchase_recipes_missing"
        if DIGITAL_ACCESS_CODES - access:
            return "tpl_postpurchase_recipes_owned"
        return None
    if notification.notification_kind == "review_followup":
        return "tpl_postpurchase_review_consultation" if "ACCESS_CONSULTATION" in access else "tpl_postpurchase_review_no_consultation"
    if notification.notification_kind == "course_stalled_72h":
        return notification.content_code or "tpl_postpurchase_tempo_late"
    if notification.notification_kind == "sales_last_chance_due":
        stage = str((notification.payload or {}).get("stage") or "")
        if stage in {"early", "second"}:
            if "ACCESS_RECIPES" not in access:
                return "tpl_postpurchase_recipes_missing"
            if DIGITAL_ACCESS_CODES - access:
                return "tpl_postpurchase_recipes_owned"
            return None
        if stage == "review":
            return (
                "tpl_postpurchase_review_consultation"
                if "ACCESS_CONSULTATION" in access
                else "tpl_postpurchase_review_no_consultation"
            )
        if stage == "last_week" and (
            DIGITAL_ACCESS_CODES - access or "ACCESS_CONSULTATION" not in access
        ):
            return "tpl_postpurchase_final_offer"
        return None
    return notification.content_code


def course_stall_is_current(session: Session, notification: MasterclassNotification) -> bool:
    if notification.notification_kind != "course_stalled_72h":
        return True
    threshold = notification.due_at - timedelta(hours=72)
    later_activity = session.execute(
        text(
            "SELECT 1 FROM masterclass_events "
            "WHERE user_id = :user_id AND occurred_at > :threshold "
            "AND id <> :event_id LIMIT 1"
        ),
        {
            "user_id": notification.user_id,
            "threshold": threshold,
            "event_id": notification.event_id,
        },
    ).first()
    completed = session.execute(
        text(
            "SELECT 1 FROM masterclass_events "
            "WHERE user_id = :user_id AND event_type = 'masterclass_completed' LIMIT 1"
        ),
        {"user_id": notification.user_id},
    ).first()
    return later_activity is None and completed is None


def rendered(item: ContentItem, values: dict[str, str]) -> SimpleNamespace:
    body = item.body_source
    for key, value in values.items():
        body = body.replace("{{" + key + "}}", value)
    return SimpleNamespace(
        code=item.code,
        title=item.title,
        body_source=body,
        media_kind=item.media_kind,
        media_path=item.media_path,
        telegram_file_id=item.telegram_file_id,
    )


def dispatch_due_masterclass_notifications(
    session: Session,
    sender,
    offers_url: str,
    access_resolver: Callable[[Session, str], set[str]] = crm_access_codes,
) -> dict[str, int]:
    counters = {"sent": 0, "skipped": 0, "waiting_contact": 0, "failed": 0}
    due = list(session.scalars(
        select(MasterclassNotification)
        .where(MasterclassNotification.status == "pending", MasterclassNotification.due_at <= datetime.now(UTC))
        .order_by(MasterclassNotification.due_at, MasterclassNotification.created_at)
    ))
    for notification in due:
        if notification.notification_kind == "owner_closing_review":
            continue
        contact = session.scalar(
            select(Contact)
            .where(Contact.user_id == notification.user_id, Contact.status == "active")
            .order_by(Contact.last_seen_at.desc())
        )
        if not contact:
            counters["waiting_contact"] += 1
            continue
        access = access_resolver(session, notification.user_id)
        if "ACCESS_MASTERCLASS" not in access:
            notification.status = "skipped"
            notification.error_message = "masterclass access is no longer active"
            counters["skipped"] += 1
            continue
        if not course_stall_is_current(session, notification):
            notification.status = "skipped"
            notification.error_message = "course activity resumed or course completed"
            counters["skipped"] += 1
            continue
        code = content_code_for(notification, access)
        if not code:
            notification.status = "skipped"
            notification.error_message = "nothing relevant to send"
            counters["skipped"] += 1
            continue
        item = session.scalar(select(ContentItem).where(ContentItem.code == code))
        if not item or item.status not in {"published", "draft"}:
            notification.status = "failed"
            notification.error_message = f"content not found: {code}"
            counters["failed"] += 1
            continue
        values = {
            "offers_url": offers_url or "[ссылка на актуальные предложения]",
            "offer_expires_at": "срок указан на странице предложения",
        }
        content = rendered(item, values)
        log = ManualMessage(contact_id=contact.id, direction="out", body_source=content.body_source, status="pending", operator_email="system:masterclass")
        session.add(log)
        try:
            log.platform_message_id = sender.send_content(contact.chat_id, content, {})
            log.status = "sent"
            notification.status = "sent"
            notification.sent_at = datetime.now(UTC)
            notification.error_message = None
            counters["sent"] += 1
        except Exception as exc:
            log.status = "failed"
            notification.error_message = str(exc)[:2000]
            counters["failed"] += 1
    session.commit()
    return counters
