from copy import deepcopy

import pytest
from sqlalchemy import select

from app.app_routes import BASE_STRENGTH_EXERCISES
from app.models import AdminAppEdit, StrengthState
from app.strength_templates import template_exercise_settings
from test_admin_apps import add_user, login, make_client


TYPES = [{"workout_type": 1, "title": "Верх", "active": True},
         {"workout_type": 2, "title": "Низ", "active": True},
         {"workout_type": 3, "title": "Архив", "active": False}]


def test_membership_replaces_active_lists_keeps_global_custom_and_inactive_templates():
    catalog = [{"exercise_id": "a"}, {"exercise_id": "custom-b"}, {"exercise_id": "c"}]
    old = [{"scope": "catalog", "exercise_id": "custom-b", "exercise_name": "Свое", "source": "custom"},
           {"workout_type": 3, "exercise_id": "a", "active": True},
           {"workout_type": 1, "exercise_id": "a", "active": True, "source_note": "Импорт"}]
    before = deepcopy(old)
    result = template_exercise_settings([
        {"workout_type": 1, "exercise_ids": []},
        {"workout_type": 2, "exercise_ids": ["custom-b", "a"]}], TYPES, catalog, old)
    assert old == before and result[:2] == old[:2]
    assert all(not row["active"] for row in result[2:] if row["workout_type"] == 1)
    assert next(row for row in result if row.get("workout_type") == 1 and row.get("exercise_id") == "a")["source_note"] == "Импорт"
    active = sorted([row for row in result[2:] if row["workout_type"] == 2 and row["active"]], key=lambda r: r["sort_order"])
    assert [row["exercise_id"] for row in active] == ["custom-b", "a"]


@pytest.mark.parametrize("incoming", [None, [], [{"workout_type": 1, "exercise_ids": []}],
    [{"workout_type": True, "exercise_ids": []}, {"workout_type": 2, "exercise_ids": []}],
    [{"workout_type": 1, "exercise_ids": []}, {"workout_type": 1, "exercise_ids": []}],
    [{"workout_type": 1, "exercise_ids": []}, {"workout_type": 3, "exercise_ids": []}],
    [{"workout_type": 1, "exercise_ids": ["unknown"]}, {"workout_type": 2, "exercise_ids": []}],
    [{"workout_type": 1, "exercise_ids": ["a", "a"]}, {"workout_type": 2, "exercise_ids": []}],
    [{"workout_type": 1, "exercise_ids": [False]}, {"workout_type": 2, "exercise_ids": []}],
    [{"workout_type": 1, "exercise_ids": ["hidden"]}, {"workout_type": 2, "exercise_ids": []}]])
def test_invalid_or_incomplete_boards_are_rejected(incoming):
    with pytest.raises(ValueError):
        template_exercise_settings(incoming, TYPES, [{"exercise_id": "a"}, {"exercise_id": "hidden", "catalog_active": False}], [])


def test_one_versioned_request_moves_both_templates_and_never_changes_workout_snapshots():
    client, factory = make_client()
    a, b = [row["code"] for row in BASE_STRENGTH_EXERCISES[:2]]
    history = [{"session_id": "historical", "session_number": 1, "workout_type": 1,
                "date": "2026-11-20", "exercises": [{"exercise_id": a, "sort_order": 1, "note": "История",
                "sets": [{"fact_weight": 35, "fact_reps": 12, "plan_weight": 30, "plan_reps": 10, "rpe": 8}]}]}]
    custom = {"scope": "catalog", "exercise_id": "custom-local", "exercise_name": "Своё", "source": "custom"}
    with factory() as db:
        user = add_user(db, "board@example.test", "Редактор")
        uid = str(user.id)
        db.add(StrengthState(user_id=user.id, version=1, workout_types=deepcopy(TYPES), workouts=deepcopy(history), hidden_exercises=[custom]))
        db.commit()
    login(client)
    body = {"action": "saveWorkoutTypes", "target_user_id": uid, "version": 1, "workout_types": TYPES,
            "template_exercises": [{"workout_type": 1, "exercise_ids": [b]}, {"workout_type": 2, "exercise_ids": [a, "custom-local"]}]}
    assert client.post('/api/apps/strength', json=body).json()['version'] == 2
    for type_id, expected in [(1, [b]), (2, [a, "custom-local"])]:
        payload = client.get('/api/apps/strength', params={"action": "getWorkout", "type": type_id, "target_user_id": uid}).json()['workout']
        assert [e['exercise_id'] for e in payload['exercise_catalog'] if e['active']] == expected
    with factory() as db:
        state = db.scalar(select(StrengthState))
        assert state.workouts == history and state.version == 2
        assert custom in state.hidden_exercises
        assert len(list(db.scalars(select(AdminAppEdit)))) == 1
    assert client.post('/api/apps/strength', json=body).json()['error'] == 'STRENGTH_STATE_CONFLICT'
    body['version'] = 2
    body['workout_types'] = [{**t, 'title': 'Недопустимая правка'} for t in TYPES]
    body['template_exercises'][1]['exercise_ids'] = ['custom-foreign']
    assert client.post('/api/apps/strength', json=body).json()['ok'] is False
    with factory() as db:
        state = db.scalar(select(StrengthState))
        assert state.version == 2 and state.workouts == history and state.workout_types[0]['title'] == 'Верх'


def test_anonymous_board_write_is_denied():
    client, _ = make_client()
    assert client.post('/api/apps/strength', json={"action": "saveWorkoutTypes", "version": 1,
        "workout_types": TYPES, "template_exercises": []}).status_code == 401
