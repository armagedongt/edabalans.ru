from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape
import re
from types import SimpleNamespace
from typing import Callable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Contact, ContentItem, ManualMessage, MasterclassNotification
from app.maintenance import allowed_telegram_ids as parse_allowed_telegram_ids


DIGITAL_ACCESS_CODES = {
    "ACCESS_RECIPES",
    "ACCESS_CALORIES",
    "ACCESS_STRENGTH",
    "ACCESS_CONSULTATION_RECORDINGS",
}

ONBOARDING_QUESTION_TITLES = {
    "parameters": "Параметры",
    "main_request": "Главный запрос",
    "work": "Работа и распорядок",
    "training": "Тренировки",
    "medical": "Медицинские ограничения",
    "wellbeing": "Самочувствие",
    "habits": "Вредные привычки",
    "diet_strengths": "Питание сейчас",
    "food_budget": "Расходы на питание",
    "outside_food": "Еда вне дома",
    "calorie_history": "Опыт подсчёта калорий",
    "diet_history": "Диеты и подходы",
    "courses_history": "Другие программы",
    "mentoring": "Опыт наставничества",
    "attribution": "Как вы узнали о Сергее",
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


def client_values(
    session: Session,
    contact: Contact,
    offers_url: str,
    course_url: str,
    account_url: str,
    template_body: str,
) -> dict[str, str]:
    values = {
        "offers_url": escape(offers_url, quote=True),
        "course_url": escape(course_url or account_url, quote=True),
        "account_url": escape(account_url or course_url, quote=True),
        "offer_expires_at": "срок указан на странице предложения",
    }
    identity_keys = ("{{email}}", "{{telegram_username}}", "{{masterclass_tariff}}", "{{purchase_date}}", "{{questionnaire_formatted}}")
    if not any(key in template_body for key in identity_keys):
        return values
    email = session.execute(
        text(
            "SELECT email_original FROM user_emails WHERE user_id=:user_id "
            "ORDER BY is_primary DESC, created_at LIMIT 1"
        ),
        {"user_id": contact.user_id},
    ).scalar()
    payment = session.execute(
        text(
            "SELECT p.product_name_raw, COALESCE(p.paid_at, p.source_event_at, p.created_at) "
            "FROM user_accesses ua "
            "JOIN resources r ON r.id=ua.resource_id "
            "LEFT JOIN payments p ON p.id=ua.source_payment_id "
            "WHERE ua.user_id=:user_id AND r.code='ACCESS_MASTERCLASS' "
            "AND ua.revoked_at IS NULL "
            "AND (ua.expires_at IS NULL OR ua.expires_at > CURRENT_TIMESTAMP) "
            "ORDER BY COALESCE(p.paid_at, p.source_event_at, p.created_at) DESC LIMIT 1"
        ),
        {"user_id": contact.user_id},
    ).first()
    answers = session.execute(
        text(
            "SELECT qa.question_code, qa.answer_text FROM questionnaire_runs qr "
            "JOIN questionnaire_answers qa ON qa.run_id=qr.id "
            "WHERE qr.user_id=:user_id AND qr.kind='onboarding' "
            "ORDER BY qa.updated_at, qa.question_code"
        ),
        {"user_id": contact.user_id},
    ).all()
    questionnaire = "\n\n".join(
        f"{ONBOARDING_QUESTION_TITLES.get(str(code), str(code))}:\n{answer}"
        for code, answer in answers
        if str(answer or "").strip()
    ) or "Стартовая анкета пока не заполнена. Откройте её в первом дне Мастер-класса."
    paid_at = payment[1] if payment else None
    if paid_at and not isinstance(paid_at, datetime):
        try:
            paid_at = datetime.fromisoformat(str(paid_at))
        except ValueError:
            paid_at = None
    return {
        **values,
        "email": escape(str(email or "не найден"), quote=True),
        "telegram_username": escape(contact.username or "без username", quote=True),
        "masterclass_tariff": escape(str(payment[0] if payment and payment[0] else "доступ к Мастер-классу"), quote=True),
        "purchase_date": paid_at.strftime("%d.%m.%Y") if paid_at else "дата не указана",
        "questionnaire_formatted": escape(questionnaire, quote=True),
    }


def content_is_sendable(item: ContentItem, body: str) -> tuple[bool, str | None]:
    if item.status != "published":
        return False, "content is not published"
    if not body.strip():
        return False, "content is empty"
    if re.search(r"{{[^{}]+}}", body):
        return False, "content has unresolved variables"
    if body.lstrip().startswith("["):
        return False, "content is an editorial placeholder"
    return True, None


def dispatch_due_masterclass_notifications(
    session: Session,
    sender,
    offers_url: str,
    access_resolver: Callable[[Session, str], set[str]] = crm_access_codes,
    *,
    course_url: str = "",
    account_url: str = "",
    test_only: bool = False,
    allowed_telegram_ids: str | None = None,
) -> dict[str, int]:
    counters = {"sent": 0, "skipped": 0, "waiting_contact": 0, "test_filtered": 0, "maintenance_filtered": 0, "failed": 0}
    allowed_ids = parse_allowed_telegram_ids(allowed_telegram_ids) if allowed_telegram_ids is not None else None
    due = list(session.scalars(
        select(MasterclassNotification)
        .where(MasterclassNotification.status == "pending", MasterclassNotification.due_at <= datetime.now(UTC))
        .order_by(MasterclassNotification.due_at, MasterclassNotification.created_at)
    ))
    for notification in due:
        if notification.notification_kind == "owner_closing_review":
            continue
        if test_only:
            enabled = session.execute(
                text(
                    "SELECT 1 FROM masterclass_test_profiles "
                    "WHERE user_id=:user_id AND enabled=true LIMIT 1"
                ),
                {"user_id": notification.user_id},
            ).first()
            if not enabled:
                counters["test_filtered"] += 1
                continue
        contact = session.scalar(
            select(Contact)
            .where(Contact.user_id == notification.user_id, Contact.status == "active")
            .order_by(Contact.last_seen_at.desc())
        )
        if not contact:
            counters["waiting_contact"] += 1
            continue
        if allowed_ids is not None and contact.telegram_user_id not in allowed_ids:
            counters["maintenance_filtered"] += 1
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
        if not item:
            notification.status = "failed"
            notification.error_message = f"content not found: {code}"
            counters["failed"] += 1
            continue
        values = client_values(session, contact, offers_url, course_url, account_url, item.body_source)
        content = rendered(item, values)
        safe, reason = content_is_sendable(item, content.body_source)
        if not safe:
            notification.status = "failed"
            notification.error_message = reason
            counters["failed"] += 1
            continue
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
