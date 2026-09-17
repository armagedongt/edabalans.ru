from __future__ import annotations

import math
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import QuestionnaireAnswer, QuestionnaireRun


# Stable answer codes belong to the questionnaire, not to calculator variants.
PERSON_FIELDS = (
    {"key": "gender", "code": "person_gender", "title": "Пол", "options": ["Женщина", "Мужчина"]},
    {"key": "age", "code": "person_age", "title": "Возраст, лет", "min": 1, "max": 120, "step": 1},
    {"key": "height", "code": "person_height", "title": "Рост, см", "min": 50, "max": 250, "step": 0.1},
    {"key": "weight", "code": "person_weight", "title": "Вес, кг", "min": 10, "max": 500, "step": 0.1},
)


def normalize_person_answer(code: str, text: str) -> str:
    field = next(row for row in PERSON_FIELDS if row["code"] == code)
    text = text.strip()
    if not text:
        return ""
    if "options" in field:
        if text not in field["options"]:
            raise HTTPException(422, "Недопустимое значение пола")
        return text
    try:
        number = float(text.replace(",", "."))
    except ValueError as exc:
        raise HTTPException(422, "Введите число") from exc
    if not math.isfinite(number) or not field["min"] <= number <= field["max"]:
        raise HTTPException(422, "Значение вне допустимого диапазона")
    if field["key"] == "age" and not number.is_integer():
        raise HTTPException(422, "Возраст указывается в полных годах")
    return str(int(number)) if number.is_integer() else str(number)


def person_parameters(db: Session, user_id: uuid.UUID) -> dict:
    rows = db.execute(
        select(QuestionnaireAnswer.question_code, QuestionnaireAnswer.answer_text)
        .join(QuestionnaireRun, QuestionnaireRun.id == QuestionnaireAnswer.run_id)
        .where(QuestionnaireRun.user_id == user_id, QuestionnaireRun.kind == "onboarding")
    )
    answers = dict(rows.all())
    result = {}
    for field in PERSON_FIELDS:
        text = answers.get(field["code"], "")
        if text:
            result[field["key"]] = text if "options" in field else float(text)
    return result
