"""Authenticated, explicit delivery of one saved workout plan to its owner."""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.account_auth_routes import require_native_user
from app.app_service import AppAccessError, require_user_resource
from app.application_access_service import application_access_state
from app.app_management import application_manager
from app.config import Settings, get_settings
from app.database import get_db
from app.models import AdminAppEdit, StrengthState, User

router = APIRouter()


def html_pieces(value: str, limit: int = 2600) -> list[str]:
    pieces, current, size = [], [], 0
    for char in str(value):
        escaped = escape(char, quote=False)
        units = len(escaped.encode("utf-16-le")) // 2
        if size + units > limit:
            pieces.append("".join(current))
            current, size = [], 0
        current.append(escaped)
        size += units
    if current:
        pieces.append("".join(current))
    return pieces


def plan_messages(workout: dict, title: str, names: dict[str, str], *, exercise_only: bool = False) -> list[str]:
    kind = "упражнения" if exercise_only else "тренировки"
    heading = f"<b>Для вас подготовлен план {kind} «{escape(title)}»</b>"
    if len(heading.encode("utf-16-le")) // 2 > 700:
        raise ValueError("Слишком длинное название шаблона")
    rows, count = [], 0
    exercises = sorted(workout.get("exercises") or [], key=lambda ex: int(ex.get("sort_order") or 0))
    for number, exercise in enumerate(exercises, 1):
        sets = []
        for index, item in enumerate(exercise.get("sets") or [], 1):
            weight, reps = item.get("plan_weight"), item.get("plan_reps")
            if weight in (None, "") and reps in (None, ""):
                continue
            sets.append(f"{index}) {weight if weight not in (None, '') else '—'} кг × {reps if reps not in (None, '') else '—'}")
        if not sets:
            continue
        count += len(sets)
        emoji = "".join(char + "\ufe0f\u20e3" for char in str(number))
        name = names.get(str(exercise.get("exercise_id"))) or exercise.get("exercise_name") or "Упражнение"
        rows.extend(html_pieces(f"\n{emoji} {name}"))
        for line in sets:
            rows.extend(html_pieces(line))
        for field, label in (("coach_note", "Комментарий тренера"), ("note", "Комментарий пользователя")):
            if exercise.get(field):
                rows.extend(f"<i>* {label}: {part}</i>" for part in html_pieces(str(exercise[field])))
    if not count:
        raise ValueError("В тренировке пока нет заполненного плана")
    messages, current = [], heading
    for row in rows:
        if len((current + "\n" + row).encode("utf-16-le")) // 2 > 3800:
            messages.append(current)
            current = heading
        current += "\n" + row
    messages.append(current)
    if len(messages) > 40:
        raise ValueError("План слишком большой для одной отправки")
    return messages


class PlanDeliveryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_user_id: uuid.UUID | None = None
    session_id: str = Field(min_length=1, max_length=255)
    exercise_id: str | None = Field(default=None, min_length=1, max_length=255)
    version: int = Field(ge=0)
    request_id: uuid.UUID


def deliver_plan(settings: Settings, payload: dict) -> dict:
    if not settings.app_auth_secret:
        raise HTTPException(503, "Сервис отправки не настроен")
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    signature = hmac.new(settings.app_auth_secret.encode(), b"strength-plan\n" + raw, hashlib.sha256).hexdigest()
    request = urllib.request.Request(settings.strength_delivery_endpoint, data=raw, method="POST", headers={
        "Content-Type": "application/json", "X-Edabalans-Strength-Signature": signature,
        "User-Agent": "EdabalansWorkoutExport/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # The internal service returns only its safe public error, never transport details.
        try:
            detail = json.loads(exc.read()).get("detail")
        except (ValueError, AttributeError):
            detail = None
        if exc.code in (409, 422, 502, 503) and isinstance(detail, str):
            raise HTTPException(exc.code, detail) from None
        raise HTTPException(502, "Доставка не подтверждена. Проверьте мессенджер перед повторной отправкой.") from None
    except (OSError, ValueError, TypeError):
        raise HTTPException(502, "Доставка не подтверждена. Проверьте мессенджер перед повторной отправкой.") from None
    if (not isinstance(result, dict) or result.get("ok") is not True
            or not isinstance(result.get("message_ids"), list)
            or len(result["message_ids"]) != len(payload["messages"])
            or any(not isinstance(value, str) or not value for value in result["message_ids"])
            or result.get("platform") not in ("telegram", "max")):
        raise HTTPException(502, "Мессенджер не подтвердил доставку")
    return result


@router.post("/api/apps/strength/send-plan")
def send_plan(body: PlanDeliveryIn, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise HTTPException(415, "Требуется application/json")
    admin = None
    if body.target_user_id is not None:
        admin = application_manager(request, db)
        if not admin:
            raise HTTPException(401, "Требуется вход администратора")
        user = db.get(User, body.target_user_id)
        if user is None or user.merged_into_user_id is not None:
            raise HTTPException(404, "Профиль не найден")
    else:
        try:
            user = require_user_resource(db, require_native_user(request, db), ("strength", "ACCESS_STRENGTH"))
            if not application_access_state(db, user.id, "strength")["start_open"]:
                raise AppAccessError("Курс тренировок ещё не открыт")
        except AppAccessError as exc:
            raise HTTPException(403, str(exc)) from None
    state = db.scalar(select(StrengthState).where(StrengthState.user_id == user.id))
    if state is None:
        raise HTTPException(404, "Тренировки не найдены")
    if state.version != body.version:
        raise HTTPException(409, "Данные изменились. Загрузите актуальную версию перед отправкой")
    workout = next((item for item in state.workouts or [] if str(item.get("session_id")) == body.session_id), None)
    if workout is None:
        raise HTTPException(404, "Тренировка не найдена")
    from app.app_routes import strength_account_catalog
    names = {str(item["exercise_id"]): item.get("short_name") or item["exercise_name"] for item in strength_account_catalog(db, state)}
    title = next((str(item["title"]) for item in state.workout_types or [] if item.get("workout_type") == workout.get("workout_type")), f"Шаблон {workout.get('workout_type')}")
    selected = workout
    if body.exercise_id is not None:
        exercise = next((item for item in workout.get("exercises") or [] if str(item.get("exercise_id")) == body.exercise_id), None)
        if exercise is None:
            raise HTTPException(404, "Упражнение не найдено в этой тренировке")
        selected = {**workout, "exercises": [exercise]}
        title = names.get(body.exercise_id) or str(exercise.get("exercise_name") or "Упражнение")
    try:
        messages = plan_messages(selected, title, names, exercise_only=body.exercise_id is not None)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Проверьте заполнение плана тренировки") from None
    result = deliver_plan(settings, {
        "request_id": str(body.request_id), "user_id": str(user.id), "messages": messages,
    })
    if admin:
        db.add(AdminAppEdit(admin_username=admin, target_user_id=user.id, app_code="strength", action="sendPlan",
                            details={"session_id": body.session_id, "exercise_id": body.exercise_id, "version": state.version, "platform": result["platform"], "message_ids": result["message_ids"]}))
        db.commit()
    return result
