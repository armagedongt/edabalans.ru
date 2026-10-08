from copy import deepcopy

import pytest

from app.importers.strength_exercise_catalog import normalize_exercise_catalog


NAMES = {
    "lat-pulldown": "Тяга верхнего блока сидя",
    "assisted-pull-up": "Подтягивания в гравитроне",
    "hip-thrust": "Ягодичный мост в тренажёре",
    "hip-thrust-barbell": "Ягодичный мост со штангой",
    "machine-lateral-raise": "Разведение рук в тренажёре",
    "gravitron-single-leg-press": "Жим платформы гравитрона одной ногой",
}


def session(number, exercise_id, note=""):
    return {"session_number": number, "session_id": f"session-{number}",
            "workout_type": 1, "date": "", "status": "filled",
            "exercises": [{"exercise_id": exercise_id, "exercise_name": "Старое название",
                           "note": note, "sets": [{"plan_weight": 30, "fact_weight": "",
                                                    "fact_reps": 12, "rpe": 8}]}]}


def test_explicit_transition_splits_history_without_changing_any_results():
    workouts = [session(7, "pullup"), session(8, "pullup", "Подтягивания в гравитроне"),
                session(9, "pullup")]
    before = deepcopy(workouts)
    after, settings = normalize_exercise_catalog(workouts, [], NAMES)
    assert [w["exercises"][0]["exercise_id"] for w in after] == [
        "lat-pulldown", "assisted-pull-up", "assisted-pull-up"]
    for old, new in zip(before, after):
        assert {k: v for k, v in old.items() if k != "exercises"} == {
            k: v for k, v in new.items() if k != "exercises"}
        assert old["exercises"][0]["sets"] == new["exercises"][0]["sets"]
        assert old["exercises"][0]["note"] == new["exercises"][0]["note"]
        assert new["exercises"][0]["legacy_exercise_id"] == "pullup"
    assert workouts == before
    assert normalize_exercise_catalog(after, settings, NAMES) == (after, settings)


def test_machine_bridge_and_one_leg_platform_press_are_distinct_from_other_movements():
    after, _ = normalize_exercise_catalog([
        session(1, "hip_bridge"), session(2, "hip-thrust"),
        session(3, "hip-thrust-barbell"),
        session(4, "legacy-t2-жим-в-гравитроне-без-отдыха")], [], NAMES)
    assert [w["exercises"][0]["exercise_id"] for w in after] == [
        "hip-thrust", "hip-thrust", "hip-thrust-barbell", "gravitron-single-leg-press"]
    assert after[1]["exercises"][0]["exercise_name"] == "Ягодичный мост в тренажёре"


def test_merging_aliases_keeps_active_template_position_and_other_templates():
    settings = [
        {"exercise_id": "machine-lateral-raise", "workout_type": 2, "active": False, "sort_order": 30},
        {"exercise_id": "legacy-t2-плечи-тренажер", "workout_type": 2, "active": True, "sort_order": 4},
        {"exercise_id": "legacy-t1-плечи-тренажер", "workout_type": 1, "active": False, "sort_order": 6},
        {"scope": "catalog", "exercise_id": "custom-personal", "exercise_name": "Свое упражнение"},
    ]
    _, after = normalize_exercise_catalog([], settings, NAMES)
    assert len(after) == 3
    assert after[0]["exercise_id"] == "machine-lateral-raise"
    assert after[0]["active"] is True and after[0]["sort_order"] == 4
    assert after[1]["workout_type"] == 1 and after[1]["active"] is False
    assert after[2] == settings[3]


def test_ambiguous_mixed_history_requires_marker_instead_of_guessing_from_weights():
    with pytest.raises(ValueError, match="explicit"):
        normalize_exercise_catalog([session(1, "pullup")], [], NAMES)


def test_colliding_results_refuse_conversion_without_changing_original():
    workout = session(1, "hip_bridge")
    workout["exercises"].append(session(2, "hip-thrust")["exercises"][0])
    before = deepcopy(workout)
    with pytest.raises(ValueError, match="combine results"):
        normalize_exercise_catalog([workout], [], NAMES)
    assert workout == before
