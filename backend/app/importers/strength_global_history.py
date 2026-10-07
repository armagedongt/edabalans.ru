"""Deterministic, side-effect-free migration for legacy strength JSON history.

The database still stores one ``StrengthState`` JSON document per user.  This
module only transforms a copied JSON value; the production command that applies
it must perform backup, restore verification and a dry run first.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _valid_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def workout_sort_key(workout: dict[str, Any]) -> tuple[Any, ...]:
    """Order the person's entire history by date before filtering by template."""
    recorded_date = _valid_date(workout.get("date"))
    old_number = _integer(workout.get("legacy_session_number") or workout.get("session_number"))
    workout_type = _integer(workout.get("workout_type"))
    if recorded_date is not None:
        return (0, recorded_date.isoformat(), workout_type, old_number, str(workout.get("session_id") or ""))
    # Undated plans remain after dated history; their dates are never invented.
    return (1, "", old_number, workout_type, str(workout.get("session_id") or ""))


def migrate_workouts(workouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy and globally renumber legacy workouts without changing their contents.

    Existing dates and all exercise data are preserved. Undated plans follow
    dated history without an inferred date.
    """
    migrated = [deepcopy(item) for item in workouts if isinstance(item, dict)]
    migrated.sort(key=workout_sort_key)

    for number, workout in enumerate(migrated, 1):
        if "legacy_session_number" not in workout:
            workout["legacy_session_number"] = _integer(workout.get("session_number"))
        workout["session_number"] = number
        workout["history_schema_version"] = 2

    for workout in migrated:
        if _valid_date(workout.get("date")) is not None:
            workout.pop("date_unknown", None)
        else:
            workout["date_unknown"] = True
    return migrated


def migrate_state_workouts(state: Any) -> tuple[list[dict[str, Any]], bool]:
    """Prepare one existing StrengthState for the global-history schema.

    The caller owns locking, backup/restore verification and transaction commit.
    This function is deliberately side-effect free so a dry-run and apply use
    the exact same conversion.
    """
    before = list(getattr(state, "workouts", None) or [])
    after = migrate_workouts(before)
    changed = after != before
    return after, changed
