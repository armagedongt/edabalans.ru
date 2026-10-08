"""Dry-run first; apply a single approved profile only after backup/restore verification."""

import argparse
import json
import uuid

from sqlalchemy import select

from app.app_routes import BASE_STRENGTH_EXERCISES
from app.database import SessionLocal
from app.importers.strength_exercise_catalog import normalize_exercise_catalog
from app.models import StrengthState


def run(*, user_id: str, expected_version: int, apply: bool = False) -> dict:
    with SessionLocal() as db:
        state = db.scalar(select(StrengthState).where(
            StrengthState.user_id == uuid.UUID(user_id)
        ).with_for_update())
        if state is None:
            raise ValueError("STRENGTH_STATE_NOT_FOUND")
        if int(state.version or 0) != expected_version:
            raise ValueError("STRENGTH_STATE_CONFLICT")
        workouts, settings = normalize_exercise_catalog(
            state.workouts or [], state.hidden_exercises or [],
            {item["code"]: item["name"] for item in BASE_STRENGTH_EXERCISES},
        )
        changed = workouts != state.workouts or settings != state.hidden_exercises
        summary = {"dry_run": not apply, "changed": changed, "version_before": state.version,
                   "sessions": len(workouts), "exercise_rows": sum(len(w["exercises"]) for w in workouts)}
        if apply and changed:
            state.workouts = workouts
            state.hidden_exercises = settings
            state.version += 1
            db.commit()
        else:
            db.rollback()
        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--expected-version", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(run(user_id=arguments.user_id, expected_version=arguments.expected_version,
                         apply=arguments.apply), sort_keys=True))
