from copy import deepcopy

import pytest
from sqlalchemy import select

from app.models import StrengthState
from test_admin_apps import make_client, add_user, login


def setup_history():
    client, factory = make_client()
    session = {"session_id": "role-session", "session_number": 1, "workout_type": 1,
               "date": "2026-10-20", "exercises": [{"exercise_id": "bench_press", "sets": [
                   {"set_number": 1, "plan_weight": 20, "plan_reps": 10, "fact_weight": 20, "fact_reps": 10},
                   {"set_number": 2, "plan_weight": 60, "plan_reps": 8, "fact_weight": 60, "fact_reps": 8, "rpe": 8},
               ]}]}
    with factory() as db:
        user = add_user(db, "roles@example.test", "Роли подходов")
        user_id = str(user.id)
        db.add(StrengthState(user_id=user.id, version=1, workout_types=[],
                             workouts=[deepcopy(session)], hidden_exercises=[]))
        db.commit()
    login(client)
    return client, factory, user_id, session


def save(client, user_id, session, version):
    return client.post("/api/apps/strength", json={"action": "saveSession", "target_user_id": user_id,
                       "workout_type": 1, "session": session, "version": version}).json()


def test_set_role_round_trip_and_old_client_preservation():
    client, factory, user_id, session = setup_history()
    def load():
        return client.get("/api/apps/strength", params={"action": "getWorkout", "type": 1,
                          "target_user_id": user_id}).json()["workout"]["sets"]
    assert [row["role"] for row in load()] == ["work", "work"]
    before = deepcopy(session)
    session["exercises"][0]["sets"][0]["role"] = "warmup"
    session["exercises"][0]["sets"][1]["role"] = "work"
    assert save(client, user_id, session, 1)["ok"] is True
    assert [row["role"] for row in load()] == ["warmup", "work"]
    # A pre-release client only edits reps; absence of role must preserve the mark.
    old_client = deepcopy(before)
    old_client["exercises"][0]["sets"][1]["plan_reps"] = 9
    assert save(client, user_id, old_client, 2)["ok"] is True
    assert [row["role"] for row in load()] == ["warmup", "work"]
    with factory() as db:
        rows = db.scalar(select(StrengthState)).workouts[0]["exercises"][0]["sets"]
        assert rows[0]["fact_weight"] == 20
        assert rows[1]["fact_reps"] == 8
        assert rows[1]["rpe"] == 8
    session["exercises"][0]["sets"][0]["role"] = "work"
    assert save(client, user_id, session, 3)["ok"] is True
    assert load()[0]["role"] == "work"


@pytest.mark.parametrize("invalid", [None, "warm-up", "", [], {}, 1])
def test_invalid_set_role_does_not_write(invalid):
    client, factory, user_id, session = setup_history()
    before = deepcopy(session)
    session["exercises"][0]["sets"][0]["role"] = invalid
    assert save(client, user_id, session, 1)["error"] == "INVALID_SET_ROLE"
    with factory() as db:
        state = db.scalar(select(StrengthState))
        assert state.version == 1
        assert state.workouts == [before]
