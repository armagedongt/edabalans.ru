from __future__ import annotations

from app.importers.strength_global_history import migrate_state_workouts, migrate_workouts


def test_migrate_workouts_preserves_ids_sets_and_uses_legacy_column_order() -> None:
    source = [
        {"session_id": "late-t2", "workout_type": 2, "session_number": 1, "legacy_group": "column_8", "date": ""},
        {"session_id": "early-t2", "workout_type": 2, "session_number": 1, "legacy_group": "column_2", "date": "2026-09-03", "exercises": [{"sets": [{"fact_weight": "20"}]}]},
        {"session_id": "early-t1", "workout_type": 1, "session_number": 1, "legacy_group": "column_2", "date": ""},
    ]

    migrated = migrate_workouts(source)

    assert [item["session_id"] for item in migrated] == ["early-t1", "early-t2", "late-t2"]
    assert [item["session_number"] for item in migrated] == [1, 2, 3]
    assert [item["legacy_session_number"] for item in migrated] == [1, 1, 1]
    assert migrated[0]["date"] == ""
    assert migrated[0]["date_unknown"] is True
    assert migrated[2]["date"] == "2026-09-03"
    assert migrated[2]["date_inferred"] is True
    assert migrated[1]["exercises"][0]["sets"][0]["fact_weight"] == "20"


def test_migrate_workouts_is_idempotent() -> None:
    source = [{"session_id": "app", "session_number": 9, "created_at": "2026-09-02T10:00:00+00:00", "date": ""}]
    assert migrate_workouts(migrate_workouts(source)) == migrate_workouts(source)


def test_migrate_app_created_history_uses_timestamps_then_id_without_losing_provenance() -> None:
    source = [
        {"session_id": "z", "session_number": 4, "created_at": "2026-09-04T10:00:00+00:00", "updated_at": "2026-09-05T10:00:00+00:00", "exercises": [{"exercise_id": "a", "sets": [{"fact_weight": "30"}]}]},
        {"session_id": "b", "session_number": 2, "created_at": "2026-09-02T10:00:00+00:00", "updated_at": "2026-09-09T10:00:00+00:00"},
        {"session_id": "a", "session_number": 3, "created_at": "2026-09-02T10:00:00+00:00", "updated_at": "2026-09-09T10:00:00+00:00"},
    ]

    migrated = migrate_workouts(source)

    assert [item["session_id"] for item in migrated] == ["a", "b", "z"]
    assert [item["session_number"] for item in migrated] == [1, 2, 3]
    assert [item["legacy_session_number"] for item in migrated] == [3, 2, 4]
    assert migrated[2]["exercises"][0]["sets"][0]["fact_weight"] == "30"
    assert source[0]["session_number"] == 4


def test_existing_state_conversion_is_dry_run_safe_before_apply() -> None:
    class State:
        workouts = [
            {"session_id": "t2", "workout_type": 2, "session_number": 1, "legacy_group": "column_2"},
            {"session_id": "t1", "workout_type": 1, "session_number": 1, "legacy_group": "column_1"},
        ]

    state = State()
    migrated, changed = migrate_state_workouts(state)

    assert changed is True
    assert [item["session_id"] for item in migrated] == ["t1", "t2"]
    assert [item["session_number"] for item in migrated] == [1, 2]
    assert [item["session_number"] for item in state.workouts] == [1, 1]
