"""Dry-run or apply the global session-history conversion for StrengthState.

Run a backup and restoration check first.  The default mode changes nothing;
``--apply`` is intentionally explicit and is for the approved production
operation only.
"""

from __future__ import annotations

import argparse
import json
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.importers.strength_global_history import migrate_state_workouts
from app.models import StrengthState


def run(*, apply: bool, user_id: str | None = None, expected_version: int | None = None, details: bool = False) -> dict:
    if apply and (not user_id or expected_version is None):
        raise ValueError("Apply requires an approved user_id and expected_version")
    if details and not user_id:
        raise ValueError("Details require a single user_id")
    summary: dict = {
        "dry_run": not apply,
        "states_scanned": 0,
        "states_changed": 0,
        "workouts": 0,
    }
    with SessionLocal() as db:
        query = select(StrengthState).order_by(StrengthState.user_id).with_for_update()
        if user_id:
            query = query.where(StrengthState.user_id == uuid.UUID(user_id))
        states = list(db.scalars(query))
        if user_id and not states:
            raise ValueError("STRENGTH_STATE_NOT_FOUND")
        for state in states:
            if expected_version is not None and int(state.version or 0) != expected_version:
                raise ValueError("STRENGTH_STATE_CONFLICT")
            after, changed = migrate_state_workouts(state)
            summary["states_scanned"] += 1
            summary["workouts"] += len(after)
            if details:
                before_by_id = {str(item.get("session_id")): item for item in state.workouts}
                summary["version_before"] = state.version
                summary["number_changes"] = [
                    {"template": item.get("workout_type"), "old": before_by_id[str(item.get("session_id"))].get("session_number"), "new": item["session_number"], "date": item.get("date")}
                    for item in after
                ]
            if not changed:
                continue
            summary["states_changed"] += 1
            if apply:
                state.workouts = after
                state.version = max(1, int(state.version or 0)) + 1
        if apply:
            db.commit()
        else:
            db.rollback()
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--user-id")
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--details", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(run(apply=arguments.apply, user_id=arguments.user_id, expected_version=arguments.expected_version, details=arguments.details), ensure_ascii=False, sort_keys=True))
