from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models import MasterclassNotification, StrengthState, TelegramTrackingEvent, UserEmail
from app.strength_completion import KIND, workout_complete
from test_admin_apps import login
from test_strength_coach_permissions import native  # noqa: F401
from test_strength_delivery import api  # noqa: F401


def prepared(native, *, source="app", filled=False):
    client, factory, uid, _ = native
    with factory() as db:
        state = db.scalar(select(StrengthState).where(StrengthState.user_id == UUID(uid)))
        workout = deepcopy(state.workouts[0])
        workout.update(date="2026-11-21", source=source)
        workout["exercises"][0]["sets"] = [
            {"plan_weight": 0, "plan_reps": 12, "fact_weight": 0 if filled else "",
             "fact_reps": 12 if filled else "", "rpe": "", "role": "work"},
            {"role": "warmup", "fact_weight": "", "fact_reps": ""}]
        state.workouts = [workout]
        db.commit()
    return client, factory, uid, workout


def save(client, workout, version=4, headers=None, **kwargs):
    return client.post("/api/apps/strength", headers=headers, json={"action": "saveSession", "version": version,
                       "workout_type": 2, "session": workout, **kwargs})


def test_native_completion_creates_one_durable_event_and_outbox_without_rpe(native):
    client, factory, uid, workout = prepared(native)
    row = workout["exercises"][0]["sets"][0]
    row.update(fact_weight=0)
    assert save(client, workout).json()["ok"]
    with factory() as db:
        assert db.scalar(select(MasterclassNotification)) is None
    row.update(fact_reps=12)
    assert save(client, workout, 5).json()["ok"]
    assert save(client, workout, 6).json()["ok"]
    # Undo, then redo must retain the original completion and delivery identity.
    row["fact_reps"] = ""
    assert save(client, workout, 7).json()["ok"]
    row["fact_reps"] = 12
    assert save(client, workout, 8).json()["ok"]
    with factory() as db:
        events = list(db.scalars(select(TelegramTrackingEvent).where(TelegramTrackingEvent.event_type == KIND)))
        alerts = list(db.scalars(select(MasterclassNotification)))
        assert len(events) == len(alerts) == 1
        event, alert = events[0], alerts[0]
        assert str(event.user_id) == uid and alert.payload["workout_date"] == "2026-11-21"
        assert alert.payload["session_number"] == 3 and alert.payload["completed_at"] == event.metadata_json["completed_at"]
        assert "Клиент потренировался" in alert.payload["message_text"]
        completion_time = datetime.fromisoformat(alert.payload["completed_at"]).astimezone(timezone(timedelta(hours=3)))
        for line in ["Клиент: Получатель", "Тренировка №3", "Дата тренировки: 2026-11-21",
                     "Шаблон: Верх", f"Завершение зафиксировано: {completion_time:%d.%m.%Y %H:%M:%S} МСК (UTC+3)"]:
            assert line in alert.payload["message_text"]


@pytest.mark.parametrize("case", ["admin", "owner", "managed", "restored", "imported", "already_complete"])
def test_non_client_completion_or_history_never_notifies(native, case, monkeypatch):
    client, factory, uid, workout = prepared(native, source="google" if case == "imported" else "app",
                                            filled=case == "already_complete")
    workout["exercises"][0]["sets"][0].update(fact_weight=0, fact_reps=12)
    kwargs = {}
    if case == "admin":
        login(client)
        kwargs["target_user_id"] = uid
    if case in {"owner", "managed"}:
        from app.account_auth_routes import ACCOUNT_MANAGER_EMAIL, ACCOUNT_VIEW_HEADER
        with factory() as db:
            email = db.scalar(select(UserEmail).where(UserEmail.user_id == UUID(uid)))
            email.email_normalized = ACCOUNT_MANAGER_EMAIL
            db.commit()
        if case == "managed":
            import app.main
            monkeypatch.setattr(app.main, "SessionLocal", factory)
            kwargs["headers"] = {ACCOUNT_VIEW_HEADER: native[3]}
    if case == "restored":
        kwargs["restore_session_number"] = True
    assert save(client, workout, **kwargs).json()["ok"]
    with factory() as db:
        assert db.scalar(select(MasterclassNotification)) is None
        assert db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.event_type == KIND)) is None


def test_partial_blank_working_rows_and_non_finite_facts_are_not_completion():
    complete = {"date": "2026-11-21", "exercises": [{"sets": [{"fact_weight": 0, "fact_reps": 12}]}]}
    assert workout_complete(complete)
    for weight, reps in [("", 12), (0, ""), (0, 0), (float("nan"), 12), (0, float("inf"))]:
        draft = deepcopy(complete)
        draft["exercises"][0]["sets"][0].update(fact_weight=weight, fact_reps=reps)
        assert not workout_complete(draft)
    complete["exercises"][0]["sets"].append({})
    assert not workout_complete(complete)
