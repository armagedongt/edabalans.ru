"""Deterministic, side-effect-free migration for legacy strength JSON history.

The database still stores one ``StrengthState`` JSON document per user.  This
module only transforms a copied JSON value; the production command that applies
it must perform backup, restore verification and a dry run first.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import re
from typing import Any


_LEGACY_COLUMN = re.compile(r"(?:^|_)column_(\d+)(?:$|_)", re.IGNORECASE)


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _legacy_column(value: Any) -> int | None:
    match = _LEGACY_COLUMN.search(str(value or ""))
    return int(match.group(1)) if match else None


def _valid_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def workout_sort_key(workout: dict[str, Any]) -> tuple[Any, ...]:
    """Return the stable global order prescribed for old mixed histories."""
    column = _legacy_column(workout.get("legacy_group"))
    if column is not None:
        return (
            0,
            column,
            _integer(workout.get("workout_type")),
            _integer(workout.get("legacy_session_number") or workout.get("session_number")),
            str(workout.get("session_id") or ""),
        )
    return (
        1,
        str(workout.get("created_at") or ""),
        str(workout.get("updated_at") or ""),
        str(workout.get("session_id") or ""),
    )


def migrate_workouts(workouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy and globally renumber legacy workouts without changing their contents.

    Missing dates are marked rather than invented when no preceding/adjacent
    source date exists.  Inferred dates never participate in ordering.
    """
    migrated = [deepcopy(item) for item in workouts if isinstance(item, dict)]
    migrated.sort(key=workout_sort_key)

    for number, workout in enumerate(migrated, 1):
        if "legacy_session_number" not in workout:
            workout["legacy_session_number"] = _integer(workout.get("session_number"))
        workout["session_number"] = number
        workout["history_schema_version"] = 2

    original_dates = [_valid_date(item.get("date")) for item in migrated]
    for index, workout in enumerate(migrated):
        if original_dates[index] is not None:
            workout.pop("date_unknown", None)
            continue
        previous = next((original_dates[pos] for pos in range(index - 1, -1, -1) if original_dates[pos]), None)
        following = next((original_dates[pos] for pos in range(index + 1, len(migrated)) if original_dates[pos]), None)
        if previous and following:
            inferred = previous + timedelta(days=(following - previous).days // 2)
        else:
            inferred = previous
        if inferred is None:
            workout["date"] = ""
            workout["date_unknown"] = True
            workout.pop("date_inferred", None)
        else:
            workout["date"] = inferred.isoformat()
            workout["date_inferred"] = True
            workout.pop("date_unknown", None)
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
