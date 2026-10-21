from copy import deepcopy

import pytest
from sqlalchemy import select

from app.models import StrengthState
from test_admin_apps import make_client, add_user, login


def comment_client():
    client, factory = make_client()
    history = [{"session_id": "old", "session_number": 1, "workout_type": 1,
                "date": "2026-10-10", "exercises": [
                    {"exercise_id": "bench_press", "exercise_name": "Жим лёжа",
                     "note": "Старое пользовательское примечание", "sets": []}]}]
    with factory() as db:
        user = add_user(db, "comments@example.test", "Комментарии")
        user_id = str(user.id)
        db.add(StrengthState(user_id=user.id, version=1, workout_types=[],
                             workouts=deepcopy(history), hidden_exercises=[]))
        db.commit()
    return client, factory, user_id, history


def load(client, user_id):
    return client.get("/api/apps/strength", params={
        "action": "getWorkout", "target_user_id": user_id, "type": 1,
    }).json()["workout"]["session_exercises"][0]


def save(client, user_id, session, version):
    return client.post("/api/apps/strength", json={
        "action": "saveSession", "target_user_id": user_id, "workout_type": 1,
        "session": session, "version": version,
    })


def test_old_user_comment_and_two_independent_comments_round_trip():
    client, factory, user_id, history = comment_client()
    login(client)
    old = load(client, user_id)
    assert old["note"] == history[0]["exercises"][0]["note"]
    assert old["coach_note"] == ""
    session = deepcopy(history[0])
    exercise = session["exercises"][0]
    exercise.update(note="Пользователь <>&\nстрока2", coach_note="Тренер <>&\nстрока2")
    assert save(client, user_id, session, 1).json()["ok"] is True
    assert (load(client, user_id)["note"], load(client, user_id)["coach_note"]) == (
        exercise["note"], exercise["coach_note"])
    # Old clients do not know coach_note and must not erase it on unrelated edits.
    del exercise["coach_note"]
    exercise["note"] = "Изменил пользователь"
    assert save(client, user_id, session, 2).json()["ok"] is True
    assert load(client, user_id)["coach_note"] == "Тренер <>&\nстрока2"
    exercise["coach_note"] = ""
    assert save(client, user_id, session, 3).json()["ok"] is True
    assert load(client, user_id)["coach_note"] == ""
    with factory() as db:
        state = db.scalar(select(StrengthState))
        assert state.workouts[0]["exercises"][0]["note"] == "Изменил пользователь"
        assert state.workouts[0]["session_id"] == "old"


@pytest.mark.parametrize("coach_note", [None, {}, ["text"], "x" * 20001])
def test_invalid_coach_note_does_not_mutate_saved_comments(coach_note):
    client, factory, user_id, history = comment_client()
    login(client)
    changed = deepcopy(history[0])
    changed["exercises"][0]["coach_note"] = coach_note
    assert save(client, user_id, changed, 1).json()["error"] == "INVALID_COACH_NOTE"
    with factory() as db:
        state = db.scalar(select(StrengthState))
        assert state.workouts == history
        assert state.version == 1


def test_comments_keep_existing_auth_and_version_boundaries():
    client, factory, user_id, history = comment_client()
    changed = deepcopy(history[0])
    changed["exercises"][0]["coach_note"] = "Не потерять"
    assert save(client, user_id, changed, 1).status_code == 401
    login(client)
    assert save(client, user_id, changed, 0).json()["error"] == "STRENGTH_STATE_CONFLICT"
    with factory() as db:
        assert db.scalar(select(StrengthState)).workouts == history
