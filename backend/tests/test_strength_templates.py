from copy import deepcopy

import pytest
from sqlalchemy import select

from app.models import StrengthState, AdminAppEdit
from app.strength_templates import normalize_templates
from test_admin_apps import make_client, add_user, login


def templates():
    return [{"workout_type": n, "title": f"Шаблон {n}", "active": True, "sort_order": n} for n in (1, 2, 3)]


def test_template_order_names_addition_and_deletion_preserve_workout_history():
    client, factory = make_client()
    history = [{"session_id": "old", "session_number": 1, "workout_type": 2,
                "date": "2026-10-10", "exercises": []}]
    with factory() as db:
        user = add_user(db, "template@example.test", "Шаблоны")
        user_id = str(user.id)
        db.add(StrengthState(user_id=user.id, version=1, workout_types=templates(),
                             workouts=deepcopy(history), hidden_exercises=[]))
        db.commit()
    login(client)
    changed = [templates()[2], templates()[0], {"workout_type": 4, "title": "Тяга", "active": True}]
    result = client.post("/api/apps/strength", json={"action": "saveWorkoutTypes", "target_user_id": user_id,
                                                    "version": 1, "workout_types": changed}).json()
    assert result["ok"] is True
    assert result["version"] == 2
    assert [t["workout_type"] for t in result["workout_types"] if t["active"]] == [3, 1, 4]
    assert next(t for t in result["workout_types"] if t["workout_type"] == 2)["active"] is False
    with factory() as db:
        state = db.scalar(select(StrengthState))
        assert state.workouts == history
        assert db.scalar(select(AdminAppEdit)).action == "saveWorkoutTypes"
    payload = client.get("/api/apps/strength", params={"action": "getWorkout", "target_user_id": user_id, "type": 4}).json()
    assert payload["workout"]["sessions"][0]["session_id"] == "old"
    saved = client.post("/api/apps/strength", json={"action": "saveExerciseCatalog", "target_user_id": user_id,
                                                  "version": 2, "workout_type": 4, "exercises": []}).json()
    assert saved["ok"] is True
    assert saved["version"] == 3


def test_template_writes_require_auth_and_current_version_without_mutation():
    client, factory = make_client()
    with factory() as db:
        user = add_user(db, "protected@example.test", "Защищённый")
        user_id = str(user.id)
        db.add(StrengthState(user_id=user.id, version=8, workout_types=templates(), workouts=[], hidden_exercises=[]))
        db.commit()
    body = {"action": "saveWorkoutTypes", "target_user_id": user_id, "workout_types": templates()}
    assert client.post("/api/apps/strength", json={**body, "version": 8}).status_code == 401
    login(client)
    assert client.post("/api/apps/strength", json=body).json()["error"] == "STRENGTH_STATE_VERSION_REQUIRED"
    assert client.post("/api/apps/strength", json={**body, "version": 7}).json()["error"] == "STRENGTH_STATE_CONFLICT"
    with factory() as db:
        state = db.scalar(select(StrengthState))
        assert state.version == 8
        assert state.workout_types == templates()


@pytest.mark.parametrize("bad", [[], [{"workout_type": True}], [{"workout_type": 0}],
                                      [{"workout_type": 4, "title": "x" * 121}],
                                      [{"workout_type": 1}, {"workout_type": 1}]])
def test_invalid_template_lists_are_rejected(bad):
    with pytest.raises(ValueError):
        normalize_templates(bad, templates(), [])


def test_deleted_template_ids_cannot_be_reused_or_history_reassigned():
    previous = [{"workout_type": 2, "title": "Старый", "active": False}]
    with pytest.raises(ValueError, match="DELETED_WORKOUT_TEMPLATE"):
        normalize_templates([{"workout_type": 2}], previous, [])
    with pytest.raises(ValueError, match="WORKOUT_TEMPLATE_ID_IN_USE"):
        normalize_templates([{"workout_type": 7}], [], [{"workout_type": 7}])
