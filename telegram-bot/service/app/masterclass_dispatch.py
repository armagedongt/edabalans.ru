from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape
import re
from types import SimpleNamespace
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
ONBOARDING_QUESTION_ORDER = {code: index for index, code in enumerate(ONBOARDING_QUESTION_TITLES)}
CURRENT_DIET_QUESTION_TITLES = {
    "whole_grains": "Цельнозерновые крупы и хлеб",
    "vegetables": "Овощи",
    "fruits_berries": "Фрукты и ягоды",
    "greens": "Зелень",
    "legumes": "Бобовые",
    "nuts_seeds": "Орехи и семена",
    "animal_proteins": "Мясо, птица, рыба, яйца",
    "dairy": "Молочные продукты",
    "plant_oils": "Растительные масла",
    "animal_fats": "Сливочное масло и животные жиры",
    "sweets": "Сладости и десерты",
    "snacks_fast_food": "Снеки и фастфуд",
    "convenience_foods": "Полуфабрикаты",
    "sugary_drinks": "Сладкие напитки",
    "alcohol": "Алкоголь",
    "water_unsweetened": "Вода и несладкие напитки",
}
CURRENT_DIET_QUESTION_ORDER = {
    code: index for index, code in enumerate(CURRENT_DIET_QUESTION_TITLES)
}
MASTERCLASS_TARIFFS = {
    "MASTERCLASS_BASIC": "Минимальный",
    "MASTERCLASS_RECIPES": "Стандартный",
    "MASTERCLASS_CONSULT": "С консультацией",
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
    if notification.notification_kind in {"owner_closing_review", "dqs_support"}:
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
    if notification.notification_kind == "course_day_unopened_18h":
        return notification.content_code or "tpl_postpurchase_day_unopened"
    if notification.notification_kind == "sales_last_chance_due":
        stage = str((notification.payload or {}).get("stage") or "")
        missing_digital = DIGITAL_ACCESS_CODES - access
        if "ACCESS_CONSULTATION" in access:
            missing_digital.discard("ACCESS_CONSULTATION_RECORDINGS")
        if stage in {"early", "second"}:
            if "ACCESS_RECIPES" not in access:
                return "tpl_postpurchase_recipes_missing"
            if missing_digital:
                return "tpl_postpurchase_recipes_owned"
            return None
        if stage == "review":
            if "ACCESS_CONSULTATION" in access and not missing_digital:
                return None
            return (
                "tpl_postpurchase_review_consultation"
                if "ACCESS_CONSULTATION" in access
                else "tpl_postpurchase_review_no_consultation"
            )
        if stage == "last_week" and (
            missing_digital or "ACCESS_CONSULTATION" not in access
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


def unopened_day_is_current(session: Session, notification: MasterclassNotification) -> bool:
    if notification.notification_kind != "course_day_unopened_18h":
        return True
    day = int((notification.payload or {}).get("day") or 0)
    if day < 2:
        return False
    opened = session.execute(
        text(
            "SELECT 1 FROM masterclass_day_progress "
            "WHERE user_id=:user_id AND day_number=:day LIMIT 1"
        ),
        {"user_id": notification.user_id, "day": day},
    ).first()
    previous_completed = session.execute(
        text(
            "SELECT 1 FROM masterclass_day_progress "
            "WHERE user_id=:user_id AND day_number=:previous_day "
            "AND completed_at IS NOT NULL LIMIT 1"
        ),
        {"user_id": notification.user_id, "previous_day": day - 1},
    ).first()
    unlock_at = (notification.payload or {}).get("unlock_at")
    try:
        unlock_due = datetime.fromisoformat(str(unlock_at)) if unlock_at else None
        if unlock_due and unlock_due.tzinfo is None:
            unlock_due = unlock_due.replace(tzinfo=UTC)
    except ValueError:
        return False
    return opened is None and previous_completed is not None and (unlock_due is None or unlock_due <= datetime.now(UTC))


def sales_window_is_current(
    session: Session, notification: MasterclassNotification
) -> bool:
    if notification.notification_kind != "sales_last_chance_due":
        return True
    stage = str((notification.payload or {}).get("stage") or "")
    if stage not in {"early", "second", "review", "last_week"}:
        return False
    current = session.execute(
        text(
            "SELECT stage_code, started_at, expires_at, trigger_event_id "
            "FROM user_offers WHERE user_id=:user_id AND status='active' "
            "AND started_at <= CURRENT_TIMESTAMP AND expires_at > CURRENT_TIMESTAMP "
            "ORDER BY CASE stage_code "
            "WHEN 'last_week' THEN 4 WHEN 'review' THEN 3 "
            "WHEN 'second' THEN 2 WHEN 'early' THEN 1 ELSE 0 END DESC LIMIT 1"
        ),
        {"user_id": notification.user_id},
    ).first()
    if current is None or str(current.stage_code) != stage:
        return False
    if current.trigger_event_id and str(current.trigger_event_id) != str(notification.event_id):
        return False
    purchase = session.execute(
        text(
            "SELECT 1 FROM masterclass_events WHERE user_id=:user_id "
            "AND event_type='offer_purchase_confirmed' "
            "AND occurred_at >= :started_at AND occurred_at < :expires_at LIMIT 1"
        ),
        {
            "user_id": notification.user_id,
            "started_at": current.started_at,
            "expires_at": current.expires_at,
        },
    ).first()
    return purchase is None


def day_url(base_url: str, day: int) -> str:
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["course_day"] = str(day)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def telegram_text_parts(body: str, limit: int = 3900) -> list[str]:
    if len(body) <= limit:
        return [body]
    parts: list[str] = []
    current = ""
    for paragraph in body.split("\n\n"):
        candidate = paragraph if not current else current + "\n\n" + paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = ""
        while len(paragraph) > limit:
            cut = paragraph.rfind("\n", 0, limit)
            if cut < limit // 2:
                cut = paragraph.rfind(" ", 0, limit)
            if cut < limit // 2:
                cut = limit
            parts.append(paragraph[:cut].rstrip())
            paragraph = paragraph[cut:].lstrip()
        current = paragraph
    if current:
        parts.append(current)
    return parts


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


def questionnaire_formatted(
    session: Session,
    user_id: str,
    kind: str,
    titles: dict[str, str],
    order: dict[str, int],
    empty_text: str,
    *,
    numbered: bool = False,
) -> str:
    answers = session.execute(
        text(
            "SELECT qa.question_code, qa.answer_text FROM questionnaire_runs qr "
            "JOIN questionnaire_answers qa ON qa.run_id=qr.id "
            "WHERE qr.user_id=:user_id AND qr.kind=:kind "
            "ORDER BY qa.updated_at, qa.question_code"
        ),
        {"user_id": user_id, "kind": kind},
    ).all()
    return "\n\n".join(
        f"<b>{str(order.get(str(code), 999) + 1) + '. ' if numbered else ''}{escape(titles.get(str(code), str(code)), quote=True)}:</b>\n{escape(str(answer), quote=True)}"
        for code, answer in sorted(
            answers, key=lambda row: order.get(str(row[0]), 999)
        )
        if str(answer or "").strip()
    ) or empty_text


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
    identity_keys = ("{{email}}", "{{telegram_username}}", "{{masterclass_tariff}}", "{{purchase_date}}", "{{questionnaire_formatted}}", "{{current_diet_formatted}}")
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
            "SELECT pr.code, COALESCE(p.paid_at, p.source_event_at, p.created_at) "
            "FROM user_accesses ua "
            "JOIN resources r ON r.id=ua.resource_id "
            "LEFT JOIN payments p ON p.id=ua.source_payment_id "
            "LEFT JOIN products pr ON pr.id=p.product_id "
            "WHERE ua.user_id=:user_id AND r.code='ACCESS_MASTERCLASS' "
            "AND ua.revoked_at IS NULL "
            "AND (ua.expires_at IS NULL OR ua.expires_at > CURRENT_TIMESTAMP) "
            "ORDER BY COALESCE(p.paid_at, p.source_event_at, p.created_at) DESC LIMIT 1"
        ),
        {"user_id": contact.user_id},
    ).first()
    questionnaire = questionnaire_formatted(
        session,
        contact.user_id,
        "onboarding",
        ONBOARDING_QUESTION_TITLES,
        ONBOARDING_QUESTION_ORDER,
        "Стартовая анкета пока не заполнена. Откройте её в первом дне Мастер-класса.",
    )
    current_diet = questionnaire_formatted(
        session,
        contact.user_id,
        "current-diet",
        CURRENT_DIET_QUESTION_TITLES,
        CURRENT_DIET_QUESTION_ORDER,
        "Опросник по продуктовым категориям пока не заполнен.",
        numbered=True,
    )
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
        "masterclass_tariff": escape(MASTERCLASS_TARIFFS.get(str(payment[0]) if payment else "", "Тариф уточняется"), quote=True),
        "purchase_date": paid_at.strftime("%d.%m.%Y") if paid_at else "дата не указана",
        "questionnaire_formatted": questionnaire,
        "current_diet_formatted": current_diet,
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
    notification_kinds: set[str] | None = None,
) -> dict[str, int]:
    counters = {"sent": 0, "skipped": 0, "waiting_contact": 0, "test_filtered": 0, "maintenance_filtered": 0, "failed": 0}
    allowed_ids = parse_allowed_telegram_ids(allowed_telegram_ids) if allowed_telegram_ids is not None else None
    due_query = (
        select(MasterclassNotification)
        .where(MasterclassNotification.status == "pending", MasterclassNotification.due_at <= datetime.now(UTC))
        .order_by(MasterclassNotification.due_at, MasterclassNotification.created_at)
    )
    if notification_kinds is not None:
        due_query = due_query.where(MasterclassNotification.notification_kind.in_(notification_kinds))
    due = list(session.scalars(due_query))
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
        if not unopened_day_is_current(session, notification):
            notification.status = "skipped"
            notification.error_message = "day was opened or is not available"
            counters["skipped"] += 1
            continue
        if not sales_window_is_current(session, notification):
            notification.status = "skipped"
            notification.error_message = "offer window expired, changed, or was purchased"
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
        payload = notification.payload or {}
        target_day = int(payload.get("day") or 0)
        if notification.notification_kind == "course_stalled_72h":
            current = session.execute(
                text(
                    "SELECT day_number, completed_at FROM masterclass_day_progress "
                    "WHERE user_id=:user_id ORDER BY day_number DESC LIMIT 1"
                ),
                {"user_id": notification.user_id},
            ).first()
            target_day = int(current.day_number if current else 1)
            if current and current.completed_at is not None:
                target_day = min(target_day + 1, 21)
            payload = {**payload, "day_title": None}
        if target_day > 0:
            title = str(payload.get("day_title") or f"День {target_day}")
            base_course_url = course_url or account_url
            values.update({
                "day_number": str(target_day),
                "day_title": escape(title, quote=True),
                "day_url": escape(day_url(base_course_url, target_day), quote=True),
            })
        content = rendered(item, values)
        safe, reason = content_is_sendable(item, content.body_source)
        if not safe:
            notification.status = "failed"
            notification.error_message = reason
            counters["failed"] += 1
            continue
        try:
            parts = telegram_text_parts(content.body_source) if not content.media_kind else [content.body_source]
            for part in parts:
                part_content = SimpleNamespace(**content.__dict__)
                part_content.body_source = part
                log = ManualMessage(contact_id=contact.id, direction="out", body_source=part, status="pending", operator_email="system:masterclass")
                session.add(log)
                log.platform_message_id = sender.send_content(contact.chat_id, part_content, {})
                log.status = "sent"
            notification.status = "sent"
            notification.sent_at = datetime.now(UTC)
            notification.error_message = None
            counters["sent"] += 1
        except Exception as exc:
            if "log" in locals():
                log.status = "failed"
            notification.error_message = str(exc)[:2000]
            counters["failed"] += 1
    session.commit()
    return counters
