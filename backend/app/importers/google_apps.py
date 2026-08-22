from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.app_service import normalize_email
from app.database import SessionLocal
from app.models import (
    DqsState,
    ImportBatch,
    Resource,
    StrengthExercise,
    StrengthState,
    User,
    UserAccess,
    UserEmail,
)


def records(values: list[list[Any]]) -> list[dict[str, Any]]:
    if not values:
        return []
    headers = [str(value) for value in values[0]]
    result = []
    for row in values[1:]:
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        if any(value not in (None, "") for value in padded):
            result.append(dict(zip(headers, padded, strict=False)))
    return result


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"false", "0", "no", "нет", "inactive", "block"}:
        return False
    if text in {"true", "1", "yes", "да", "active"}:
        return True
    return default


def json_value(value: Any) -> Any:
    if value in (None, ""):
        return None


def sheet_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date().isoformat()
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return None


def user_for_email(db, email: str, display_name: str = "") -> User:
    normalized = normalize_email(email)
    existing_email = db.scalar(select(UserEmail).where(UserEmail.email_normalized == normalized))
    if existing_email:
        user = db.get(User, existing_email.user_id)
        if user and display_name and not user.display_name:
            user.display_name = display_name
        return user
    user = User(display_name=display_name or None, status="active", data_origin="legacy_import", first_seen_at=datetime.now(timezone.utc))
    db.add(user)
    db.flush()
    db.add(UserEmail(user_id=user.id, email_original=email, email_normalized=normalized, is_primary=True, verification_status="legacy_unverified", source="google_apps", first_seen_at=datetime.now(timezone.utc)))
    db.flush()
    return user


def grant(db, user_id: uuid.UUID, resource_code: str, source: str) -> None:
    resource = db.scalar(select(Resource).where(Resource.code == resource_code))
    if not resource:
        raise RuntimeError(f"Missing resource: {resource_code}")
    exists = db.scalar(
        select(UserAccess).where(
            UserAccess.user_id == user_id,
            UserAccess.resource_id == resource.id,
            UserAccess.source == source,
            UserAccess.revoked_at.is_(None),
        )
    )
    if not exists:
        db.add(UserAccess(user_id=user_id, resource_id=resource.id, source=source, granted_at=datetime.now(timezone.utc)))


def import_dqs(db, payload: dict[str, Any], summary: dict[str, int]) -> None:
    allowed = records(payload.get("dqs_access", []))
    for row in allowed:
        email = normalize_email(row.get("email"))
        if not email or not as_bool(row.get("status (active / block / blank)"), True):
            continue
        user = user_for_email(db, email)
        grant(db, user.id, "dqs", "google_dqs_allowed")
        summary["dqs_accesses"] += 1

    for row in records(payload.get("dqs_data", [])):
        email = normalize_email(row.get("email"))
        if not email:
            continue
        user = user_for_email(db, email)
        grant(db, user.id, "dqs", "google_dqs_data")
        days = {}
        for number in range(1, 31):
            value = json_value(row.get(f"day_{number:02d}"))
            if value is not None:
                days[str(number)] = value
        state = db.scalar(select(DqsState).where(DqsState.user_id == user.id))
        if not state:
            state = DqsState(user_id=user.id, source="google_dqs")
            db.add(state)
        state.start_date = sheet_date(row.get("start_date"))
        state.days = days
        state.source = "google_dqs"
        state.version = max(1, state.version or 1)
        summary["dqs_states"] += 1


def import_strength(db, payload: dict[str, Any], summary: dict[str, int]) -> None:
    users = records(payload.get("strength_users", []))
    user_ids: dict[str, User] = {}
    for row in users:
        email = normalize_email(row.get("email"))
        if not email:
            continue
        user = user_for_email(db, email, str(row.get("display_name") or ""))
        user_ids[str(row.get("user_id"))] = user
        if as_bool(row.get("status"), True):
            grant(db, user.id, "strength", "google_strength_users")
        summary["strength_users"] += 1

    type_rows = records(payload.get("strength_types", []))
    catalog_rows = records(payload.get("strength_catalog", []))
    session_rows = records(payload.get("strength_sessions", []))
    exercise_rows = records(payload.get("strength_session_exercises", []))
    set_rows = records(payload.get("strength_sets", []))

    global_exercises: dict[str, dict[str, Any]] = {}
    for row in catalog_rows:
        code = str(row.get("exercise_id") or "").strip()
        if not code:
            continue
        item = global_exercises.setdefault(code, {"name": str(row.get("exercise_name") or code), "types": set(), "order": as_int(row.get("sort_order"), 0)})
        item["types"].add(as_int(row.get("workout_type"), 1))
        item["order"] = min(item["order"], as_int(row.get("sort_order"), item["order"]))
    for code, item in global_exercises.items():
        exercise = db.scalar(select(StrengthExercise).where(StrengthExercise.code == code))
        if not exercise:
            exercise = StrengthExercise(code=code, name=item["name"])
            db.add(exercise)
        exercise.name = item["name"]
        exercise.sort_order = item["order"]
        exercise.metadata_json = {"workout_types": sorted(item["types"]), "source": "google_strength"}
    summary["strength_exercises"] = len(global_exercises)

    exercises_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sets_by_session_exercise: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in set_rows:
        key = (str(row.get("session_id")), str(row.get("exercise_id")))
        sets_by_session_exercise[key].append({key_name: row.get(key_name, "") for key_name in (
            "set_number", "plan_weight", "plan_reps", "fact_weight", "fact_reps", "rpe",
            "plan_weight_raw", "plan_reps_raw", "fact_weight_raw", "fact_reps_raw", "rpe_raw", "source")})
    for row in exercise_rows:
        session_id = str(row.get("session_id"))
        exercise_id = str(row.get("exercise_id"))
        sets = sets_by_session_exercise[(session_id, exercise_id)]
        sets.sort(key=lambda item: as_int(item.get("set_number"), 0))
        exercises_by_session[session_id].append({
            "exercise_id": exercise_id,
            "exercise_name": str(row.get("exercise_name") or ""),
            "sort_order": as_int(row.get("sort_order"), 0),
            "note": str(row.get("note") or ""),
            "source": str(row.get("source") or "google_strength"),
            "sets": sets,
        })
    for values in exercises_by_session.values():
        values.sort(key=lambda item: item["sort_order"])

    for legacy_id, user in user_ids.items():
        workout_types = [
            {"workout_type": as_int(row.get("workout_type"), 1), "title": str(row.get("title") or ""), "active": as_bool(row.get("active"), True), "sort_order": as_int(row.get("sort_order"), 0)}
            for row in type_rows if str(row.get("user_id")) == legacy_id
        ]
        settings = [
            {"exercise_id": str(row.get("exercise_id")), "workout_type": as_int(row.get("workout_type"), 1), "active": as_bool(row.get("active"), True), "sort_order": as_int(row.get("sort_order"), 0)}
            for row in catalog_rows if str(row.get("user_id")) == legacy_id
        ]
        workouts = []
        for row in session_rows:
            if str(row.get("user_id")) != legacy_id:
                continue
            session_id = str(row.get("session_id"))
            workouts.append({
                "session_id": session_id,
                "workout_type": as_int(row.get("workout_type"), 1),
                "session_number": as_int(row.get("session_number"), 0),
                "date": str(row.get("date") or "")[:10],
                "status": str(row.get("status") or "planned"),
                "legacy_group": str(row.get("legacy_group") or ""),
                "source": str(row.get("source") or "google_strength"),
                "created_at": str(row.get("created_at") or ""),
                "updated_at": str(row.get("updated_at") or ""),
                "exercises": exercises_by_session.get(session_id, []),
            })
        workouts.sort(key=lambda item: (item["workout_type"], item["session_number"]))
        state = db.scalar(select(StrengthState).where(StrengthState.user_id == user.id))
        if not state:
            state = StrengthState(user_id=user.id, source="google_strength")
            db.add(state)
        state.workout_types = workout_types
        state.hidden_exercises = settings
        state.workouts = workouts
        state.source = "google_strength"
        state.version = max(1, state.version or 1)
        summary["strength_states"] += 1
        summary["strength_workouts"] += len(workouts)
        summary["strength_sets"] += sum(len(exercise["sets"]) for workout in workouts for exercise in workout["exercises"])


def run(payload: dict[str, Any], dry_run: bool) -> dict[str, int]:
    summary = defaultdict(int)
    with SessionLocal() as db:
        batch = ImportBatch(source="google_apps_direct", status="running")
        db.add(batch)
        db.flush()
        try:
            import_dqs(db, payload, summary)
            import_strength(db, payload, summary)
            batch.status = "dry_run" if dry_run else "completed"
            batch.finished_at = datetime.now(timezone.utc)
            batch.summary = dict(summary)
            if dry_run:
                db.rollback()
            else:
                db.commit()
        except Exception:
            db.rollback()
            raise
    return dict(summary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    print(json.dumps(run(payload, args.dry_run), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
