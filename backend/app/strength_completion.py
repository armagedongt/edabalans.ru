"""Client completion facts and owner alerts in the existing journey/outbox stores."""
from datetime import datetime, timedelta, timezone
from html import escape
import math

from sqlalchemy import select

from app.models import MasterclassNotification, TelegramTrackingEvent

KIND = "strength_workout_completed"


def workout_complete(workout: dict) -> bool:
    if not workout.get("date"):
        return False
    rows = [row for ex in workout.get("exercises", []) for row in ex.get("sets", [])
            if row.get("role", "work") != "warmup"]
    if not rows:
        return False
    for row in rows:
        try:
            weight, reps = float(row["fact_weight"]), float(row["fact_reps"])
        except (KeyError, TypeError, ValueError):
            return False
        if not math.isfinite(weight) or not math.isfinite(reps) or weight < 0 or reps <= 0:
            return False
    return True


def record_client_completion(db, user, state, previous: dict | None, workout: dict) -> None:
    # Existing completed history is never backfilled by a later edit.
    if (workout.get("source") != "app" or not workout_complete(workout)
            or (previous and workout_complete(previous))):
        return
    key = f"strength_completed:{user.id}:{workout['session_id']}"
    if db.scalar(select(TelegramTrackingEvent.id).where(TelegramTrackingEvent.deduplication_key == key)):
        return
    now = datetime.now(timezone.utc)
    title = next((str(t["title"]) for t in state.workout_types or []
                  if t.get("workout_type") == workout.get("workout_type")),
                 f"Шаблон {workout.get('workout_type')}")
    facts = {"app_code": "strength", "session_id": workout["session_id"],
             "session_number": workout["session_number"], "workout_date": workout["date"],
             "template_title": title, "client_name": user.display_name or "Без имени",
             "completed_at": now.isoformat(), "completion_basis": "client_saved_all_working_sets"}
    db.add(TelegramTrackingEvent(user_id=user.id, event_type=KIND, deduplication_key=key,
                                occurred_at=now, metadata_json=facts))
    moscow = now.astimezone(timezone(timedelta(hours=3)))
    message = ("<b>Клиент потренировался</b>\n"
               f"Клиент: {escape(facts['client_name'][:300])}\n"
               f"Тренировка №{facts['session_number']}\n"
               f"Дата тренировки: {escape(str(facts['workout_date']))}\n"
               f"Шаблон: {escape(title[:300])}\n"
               f"Завершение зафиксировано: {moscow:%d.%m.%Y %H:%M:%S} МСК (UTC+3)")
    db.add(MasterclassNotification(user_id=user.id, notification_kind=KIND,
                                  deduplication_key=key, due_at=now,
                                  expires_at=now + timedelta(days=7),
                                  payload={**facts, "message_text": message}, status="pending"))
