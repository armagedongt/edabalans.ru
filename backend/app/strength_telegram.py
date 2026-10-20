"""Personal owner pilot: export a saved workout without changing its contents."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import Settings, get_settings
from app.database import get_db
from app.models import AdminAppEdit, StrengthState, User

router = APIRouter()


def present(value) -> bool:
    return value is not None and str(value).strip() != ""


def has_fact(item: dict) -> bool:
    return any(present(item.get(key)) for key in ("fact_weight", "fact_reps", "rpe")) or item.get("completed") is True


def split_text(text: str, limit: int) -> list[str]:
    chunks, current, size = [], [], 0
    for char in text:
        units = 2 if ord(char) > 0xFFFF else 1
        if size + units > limit:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(char)
        size += units
    if current:
        chunks.append("".join(current))
    return chunks


def workout_messages(user_name: str, workout: dict) -> list[str]:
    exercises = workout.get("exercises") or []
    fact = any(has_fact(item) for exercise in exercises for item in exercise.get("sets", []))
    heading = (
        f"{user_name}\nТренировка №{workout.get('session_number', '—')} · "
        f"Шаблон {workout.get('workout_type', '—')} · {'Факт' if fact else 'План'}\n"
        f"Дата: {workout.get('date') or 'не назначена'}\n"
        f"ID: {workout.get('session_id', '')}"
    )
    if len(heading.encode("utf-16-le")) // 2 > 1000:
        raise ValueError("Слишком длинное название тренировки")
    lines = []
    if workout.get("source") == "model_example_at_owner_request":
        lines.append("Примерные значения из сохранённой записи; не подтверждённый результат.")
    count = 0
    for exercise in exercises:
        sets = []
        for index, item in enumerate(exercise.get("sets", []), 1):
            if fact and not has_fact(item):
                continue
            weight, reps = item.get("plan_weight"), item.get("plan_reps")
            if fact:
                # Completed/RPE-only legacy sets use the saved plan as their fact.
                implicit = item.get("completed") is True or present(item.get("rpe"))
                weight = item.get("fact_weight") if present(item.get("fact_weight")) else weight if implicit else None
                reps = item.get("fact_reps") if present(item.get("fact_reps")) else reps if implicit else None
            if not fact and not (present(weight) or present(reps)):
                continue
            row = f"{item.get('set_number') or index}. {weight if present(weight) else '—'} кг × {reps if present(reps) else '—'}"
            if fact and present(item.get("rpe")):
                row += f" · RPE {item['rpe']}"
            sets.append(row)
        if sets:
            count += len(sets)
            lines.append(str(exercise.get("exercise_name") or exercise.get("exercise_id") or "Упражнение"))
            lines.extend(sets)
            if exercise.get("note"):
                lines.append(str(exercise["note"]))
            lines.append("")
    if not count:
        raise ValueError("В тренировке пока нет плана или факта")
    if fact:
        lines.append("Показаны подходы с фактом. Подходы без факта не включены.")
    body = "\n".join(lines)
    return [heading + "\n\n" + chunk for chunk in split_text(body, 3000)]


def send_workout(settings: Settings, messages: list[str]) -> list[int]:
    recipient = settings.strength_telegram_owner_id.strip()
    if not recipient.isascii() or not recipient.isdigit() or int(recipient) <= 0:
        raise HTTPException(503, "Личный Telegram-получатель тренировок не настроен")
    if not settings.telegram_test_bot_token:
        raise HTTPException(503, "Основной Telegram-бот не настроен")
    base_url = settings.telegram_api_base_url.rstrip("/")
    # The configured Cloudflare relay rejects the stock urllib user agent (1010).
    headers = {"Content-Type": "application/json", "User-Agent": "EdabalansWorkoutExport/1.0"}
    if base_url:
        if not settings.telegram_gateway_token:
            raise HTTPException(503, "Маршрут основного Telegram-бота не настроен")
        headers.update({
            "X-Edabalans-Relay-Token": settings.telegram_gateway_token,
            "X-Telegram-Bot-Token": settings.telegram_test_bot_token,
        })
    else:
        base_url = f"https://api.telegram.org/bot{settings.telegram_test_bot_token}"
    sent = []
    for message in messages:
        body = json.dumps({"chat_id": recipient, "text": message}, ensure_ascii=False).encode()
        request = urllib.request.Request(
            f"{base_url}/sendMessage",
            data=body, headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                result = json.load(response)
            if not result.get("ok") or not isinstance(result.get("result", {}).get("message_id"), int):
                raise ValueError("invalid Telegram response")
            sent.append(result["result"]["message_id"])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            # Never propagate a token-bearing Telegram URL or automatically resend.
            raise HTTPException(502, f"Telegram не подтвердил доставку. Подтверждено частей: {len(sent)} из {len(messages)}. Проверьте чат перед повторной отправкой.") from None
    return sent


class WorkoutExport(BaseModel):
    target_user_id: uuid.UUID
    session_id: str = Field(min_length=1, max_length=255)
    version: int = Field(ge=0)


@router.post("/admin/api/apps/strength/telegram")
def export_workout(
    body: WorkoutExport,
    request: Request,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise HTTPException(415, "Требуется application/json")
    user = db.get(User, body.target_user_id)
    if user is None or user.merged_into_user_id is not None:
        raise HTTPException(404, "Профиль не найден")
    state = db.scalar(select(StrengthState).where(StrengthState.user_id == user.id))
    if state is None:
        raise HTTPException(404, "Тренировки не найдены")
    if state.version != body.version:
        raise HTTPException(409, "Данные изменились. Загрузите актуальную версию перед отправкой")
    workout = next((item for item in state.workouts or [] if item.get("session_id") == body.session_id), None)
    if workout is None:
        raise HTTPException(404, "Тренировка не найдена")
    try:
        messages = workout_messages(user.display_name or "Профиль", workout)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    message_ids = send_workout(settings, messages)
    db.add(AdminAppEdit(
        admin_username=admin, target_user_id=user.id, app_code="strength", action="sendTelegram",
        details={"session_id": body.session_id, "version": state.version, "message_ids": message_ids},
    ))
    db.commit()
    return {"ok": True, "message_ids": message_ids}
