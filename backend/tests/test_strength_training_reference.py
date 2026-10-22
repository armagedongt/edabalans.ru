from copy import deepcopy

from sqlalchemy import select

from app.app_routes import BASE_STRENGTH_EXERCISES
from app.models import StrengthState
from test_strength_set_roles import setup_history


def test_training_reference_reaches_catalog_without_changing_user_workouts():
    client, factory, user_id, _ = setup_history()
    with factory() as db:
        state = db.scalar(select(StrengthState))
        before = (deepcopy(state.workouts), state.version)
    result = client.get('/api/apps/strength', params={
        'action': 'getWorkout', 'type': 1, 'target_user_id': user_id,
    }).json()
    assert result['ok'] is True
    catalog = {row['exercise_id']: row for row in result['workout']['exercise_catalog']}
    for item in BASE_STRENGTH_EXERCISES:
        assert catalog[item['code']]['training'] == item['training']
    with factory() as db:
        state = db.scalar(select(StrengthState))
        assert (state.workouts, state.version) == before


def test_progression_policy_asset_is_javascript_and_contains_no_user_history():
    client, _, _, _ = setup_history()
    response = client.get('/assets/strength-progression-model.mjs')
    assert response.status_code == 200
    assert 'javascript' in response.headers['content-type']
    assert 'export function recommend' in response.text
    assert 'roles@example.test' not in response.text
