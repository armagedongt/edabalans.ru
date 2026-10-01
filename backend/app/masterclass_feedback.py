"""Three one-shot, post-checkpoint Masterclass feedback pulses."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    OwnerPaymentNotification, Payment, Product, QuestionnaireAnswer,
    QuestionnaireRun, Resource, User, UserAccess,
)
from app.app_service import primary_email


CUTOFF = datetime(2026, 9, 24, 21, 0, tzinfo=timezone.utc)  # 25 September, Moscow.
KINDS = {5: "feedback-day-5", 8: "feedback-day-8", 14: "feedback-day-14"}
COMMENT = "Если хотите добавить что-то конкретное — что больше всего понравилось или не понравилось в уже пройденной части Мастер-класса, — коротко напишите здесь."
DEPTH = {"code": "depth", "type": "choice", "title": "Как вам подробность объяснений?", "options": ["Хочется короче", "Нормально", "Хочется подробнее"]}
FORMAT = {"code": "format", "type": "choice", "title": "Как вам соотношение текста и видео?", "options": ["Больше текста", "Нормально", "Больше видео"]}

PULSES = {
    5: {
        "title": "Как пока проходит Мастер-класс?",
        "intro": "Это не публичный отзыв. Я собираю обратную связь, чтобы улучшить мой курс и ваш опыт от его прохождения.",
        "questions": [
            {"code": "dqs_tried", "type": "choice", "title": "Вы уже попробовали применять мою систему оценки питания (DQS)?", "options": ["Да", "Нет, пока только читаю"]},
            {"code": "dqs_rating", "type": "rating", "title": "Как вам сама система DQS?", "hint": "Понятна ли идея, удобно ли ей пользоваться и видите ли вы для себя пользу от её применения? Как бы вы оценили материалы о ней?", "low": "Не понравилась", "high": "Очень понравилась"},
            {"code": "other_rating", "type": "rating", "title": "Как бы вы оценили всю остальную часть Мастер-класса, которую уже прошли, кроме системы оценки качества питания?", "low": "Не удовлетворён(а)", "high": "Полностью удовлетворён(а)"},
            {"code": "account_rating", "type": "rating", "title": "Насколько удобно всё организовано: регистрация, личный кабинет, инструкция по созданию дневника питания?", "low": "Неудобно", "high": "Удобно"},
            DEPTH, FORMAT,
        ],
    },
    8: {
        "title": "Как вам первая часть системы рецептов?",
        "intro": "Вы прошли первую часть системы рецептов: в ней было больше теории и организации. Сами рецепты будут во второй части. Скажите, как вам этот блок?",
        "questions": [
            {"code": "recipes_tried", "type": "choice", "title": "Вы уже пробовали применять систему рецептов?", "options": ["Да", "Нет, пока только читаю"]},
            {"code": "recipes_rating", "type": "rating", "title": "Как вам идея системы рецептов?", "hint": "Понятна ли она, кажется ли удобной и применимой лично для вас?", "low": "Непонятно", "high": "Понятно"},
        ],
    },
    14: {
        "title": "Вы уже на финишной прямой",
        "intro": "Расскажите о впечатлениях от той части Мастер-класса, которую вы прошли после системы рецептов: с 9-го дня по сегодняшний день.",
        "questions": [
            {"code": "later_rating", "type": "rating", "title": "Как бы вы оценили эту часть Мастер-класса?", "hint": "Было ли интересно, узнали ли вы что-то новое и удалось ли уже что-то применить?", "low": "Не удовлетворён(а)", "high": "Полностью удовлетворён(а)"},
            DEPTH, FORMAT,
        ],
    },
}


def eligible_payment(db: Session, user: User) -> Payment | None:
    """Only the user's first real, directly paid Masterclass purchase qualifies."""
    if user.data_origin != "native":
        return None
    purchases = list(db.scalars(
        select(Payment).join(Product, Payment.product_id == Product.id)
        .where(Payment.user_id == user.id, Product.code.like("MASTERCLASS_%"), Payment.payment_status == "paid")
        .order_by(Payment.paid_at, Payment.created_at)
    ))
    if not purchases:
        return None
    payment = purchases[0]
    paid_at = payment.paid_at
    if not paid_at or (paid_at.replace(tzinfo=timezone.utc) if paid_at.tzinfo is None else paid_at) < CUTOFF:
        return None
    if payment.source != "robokassa":
        return None
    raw = payment.raw_payload or {}
    if isinstance(raw, dict) and (raw.get("test_mode") or (isinstance(raw.get("integration"), dict) and raw["integration"].get("test_mode"))):
        return None
    prior_access = db.scalar(
        select(UserAccess.id).join(Resource, UserAccess.resource_id == Resource.id)
        .where(UserAccess.user_id == user.id, Resource.code == "ACCESS_MASTERCLASS", UserAccess.granted_at < paid_at)
        .limit(1)
    )
    return None if prior_access else payment


def pulse_definition(day: int) -> dict:
    definition = PULSES[day]
    return {"day": day, "kind": KINDS[day], **definition, "comment": COMMENT}


def submitted(db: Session, user_id, day: int) -> bool:
    return bool(db.scalar(select(QuestionnaireRun.id).where(
        QuestionnaireRun.user_id == user_id,
        QuestionnaireRun.kind == KINDS[day],
        QuestionnaireRun.status == "submitted",
    )))


def should_block_completion(db: Session, user: User, day: int) -> bool:
    if day not in KINDS or submitted(db, user.id, day) or eligible_payment(db, user) is None:
        return False
    if day == 8:
        access = db.scalar(select(UserAccess.id).join(Resource, UserAccess.resource_id == Resource.id).where(
            UserAccess.user_id == user.id, Resource.code == "ACCESS_RECIPES",
            UserAccess.revoked_at.is_(None), UserAccess.paused_at.is_(None),
            (UserAccess.expires_at.is_(None) | (UserAccess.expires_at > datetime.now(timezone.utc))),
        ).limit(1))
        return bool(access)
    return True


def pending_pulse(db: Session, user: User, progress_rows: dict) -> dict | None:
    if eligible_payment(db, user) is None:
        return None
    for day in KINDS:
        progress = progress_rows.get(day)
        if not progress or progress.completed_at or not progress.task_opened_at or submitted(db, user.id, day):
            continue
        if not any((progress.checkmarks or {}).values()):
            continue
        if should_block_completion(db, user, day):
            return pulse_definition(day)
    return None


def validated_answers(day: int, answers: dict) -> dict[str, str]:
    if not isinstance(answers, dict):
        raise HTTPException(422, "Invalid feedback answers")
    required = {item["code"] for item in PULSES[day]["questions"]}
    if set(answers) - required - {"comment"}:
        raise HTTPException(422, "Unknown feedback answer")
    clean = {}
    for item in PULSES[day]["questions"]:
        answer = answers.get(item["code"])
        if item["type"] == "rating":
            if type(answer) is not int or not 1 <= answer <= 10:
                raise HTTPException(422, f"Missing or invalid answer: {item['code']}")
        elif answer not in item["options"]:
            raise HTTPException(422, f"Missing or invalid answer: {item['code']}")
        clean[item["code"]] = str(answer)
    comment = answers.get("comment", "")
    if not isinstance(comment, str) or len(comment) > 4000:
        raise HTTPException(422, "Invalid feedback comment")
    clean["comment"] = comment.strip()
    return clean


def store_feedback(db: Session, user: User, payment: Payment, day: int, answers: dict[str, str], now: datetime) -> None:
    run = QuestionnaireRun(user_id=user.id, kind=KINDS[day], version=1, status="submitted", submitted_at=now)
    db.add(run)
    db.flush()
    for code, answer in answers.items():
        db.add(QuestionnaireAnswer(run_id=run.id, question_code=code, answer_text=answer))
    labels = {item["code"]: item["title"] for item in PULSES[day]["questions"]}
    lines = [f"Обратная связь по Мастер-классу · день {day}", f"Имя: {user.display_name or 'не указано'}", f"Email: {primary_email(db, user.id)}", f"CRM: https://edabalans.ru/admin/users?user={user.id}"]
    lines.extend(f"{labels[code]}: {answers[code]}" for code in labels)
    if answers["comment"]:
        lines.append(f"Комментарий: {answers['comment']}")
    db.add(OwnerPaymentNotification(payment_id=payment.id, event_kind=KINDS[day], message_text="\n".join(lines)[:4000], status="pending", next_attempt_at=now))
