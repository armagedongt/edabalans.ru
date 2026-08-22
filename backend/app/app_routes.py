from __future__ import annotations

import json
import math
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.app_service import (
    AppAccessError,
    normalize_email,
    primary_email,
    resolve_user_for_resource,
    utc_iso,
)
from app.auth import require_admin
from app.database import get_db
from app.models import (
    AdminAppEdit,
    DqsState,
    MetabolismState,
    StrengthExercise,
    StrengthState,
    User,
)


router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parent / "static"
DAY_COUNT = 30
CATEGORY_COUNT = 17
JSONP_CALLBACK = re.compile(r"^[A-Za-z_$][0-9A-Za-z_$]*$")


def public_asset(path: Path, stable_loader: bool = False) -> FileResponse:
    response = FileResponse(path)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = "no-cache" if stable_loader else "public, max-age=300"
    return response


@router.get("/embed.js", include_in_schema=False)
def embed_loader() -> FileResponse:
    return public_asset(STATIC_DIR / "embed.js", stable_loader=True)


@router.get("/apps/{app_code}.html", include_in_schema=False)
def app_fragment(app_code: str) -> FileResponse:
    if app_code not in {"dqs", "strength", "metabolism"}:
        raise HTTPException(status_code=404, detail="app not found")
    return public_asset(STATIC_DIR / "apps" / f"{app_code}.html")


def error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def jsonp(payload: dict[str, Any], callback: str | None) -> Response:
    if callback and JSONP_CALLBACK.match(callback):
        body = f"{callback}({json.dumps(payload, ensure_ascii=False, separators=(',', ':'))});"
        return Response(body, media_type="application/javascript; charset=utf-8")
    return JSONResponse(payload)


def empty_strength_state(user_id: uuid.UUID) -> StrengthState:
    return StrengthState(
        user_id=user_id,
        workout_types=[
            {"workout_type": 1, "title": "Тренировка 1", "active": True, "sort_order": 1},
            {"workout_type": 2, "title": "Тренировка 2", "active": True, "sort_order": 2},
            {"workout_type": 3, "title": "Тренировка 3", "active": True, "sort_order": 3},
        ],
        hidden_exercises=[],
        workouts=[],
        source="app",
    )


@router.get("/api/apps/dqs")
def dqs_legacy_get(
    action: str = "ping",
    email: str = "",
    startDate: str = "",
    day: str = "",
    data: str = "",
    callback: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    try:
        if action == "ping":
            return jsonp({"ok": True, "service": "DQS", "dayCount": 30, "categoryCount": 17}, callback)
        user = resolve_user_for_resource(db, email, "dqs")
        state = db.scalar(select(DqsState).where(DqsState.user_id == user.id))
        if not state:
            state = DqsState(user_id=user.id, days={}, source="app")
            db.add(state)
            db.flush()

        if action == "openUser":
            days = [state.days.get(str(index)) for index in range(1, DAY_COUNT + 1)]
            payload = {
                "ok": True,
                "email": normalize_email(email),
                "startDate": state.start_date or "",
                "needsStartDate": not bool(state.start_date),
                "days": days,
                "version": state.version,
            }
        elif action == "setStartDate":
            date.fromisoformat(startDate)
            already = bool(state.start_date)
            if not already:
                state.start_date = startDate
                state.version += 1
            payload = {"ok": True, "startDate": state.start_date, "alreadySet": already, "version": state.version}
        elif action == "saveDay":
            day_number = int(day)
            if not 1 <= day_number <= DAY_COUNT:
                raise ValueError("INVALID_DAY")
            incoming = json.loads(data)
            portions = incoming.get("p")
            diversity = incoming.get("d")
            if not isinstance(portions, list) or len(portions) != CATEGORY_COUNT:
                raise ValueError("INVALID_PORTIONS")
            if not isinstance(diversity, list) or len(diversity) != CATEGORY_COUNT:
                raise ValueError("INVALID_DIVERSITY")
            normalized_portions = []
            for value in portions:
                number = float(value)
                if not math.isfinite(number) or number < 0 or abs(number * 2 - round(number * 2)) > 0.000001:
                    raise ValueError("PORTION_MUST_BE_HALF_STEP")
                normalized_portions.append(round(number * 2) / 2)
            if any(value not in (True, False, None) for value in diversity):
                raise ValueError("INVALID_DIVERSITY_VALUE")
            saved = {
                "v": 2,
                "updated": datetime.now(timezone.utc).isoformat(),
                "p": normalized_portions,
                "d": diversity,
            }
            next_days = dict(state.days or {})
            next_days[str(day_number)] = saved
            state.days = next_days
            state.version += 1
            payload = {"ok": True, "data": saved, "version": state.version}
        else:
            payload = error("UNKNOWN_ACTION")
        db.commit()
        return jsonp(payload, callback)
    except (AppAccessError, ValueError, TypeError, json.JSONDecodeError) as exc:
        db.rollback()
        return jsonp(error(str(exc)), callback)


def strength_payload(db: Session, state: StrengthState, user_id: uuid.UUID, workout_type: int) -> dict[str, Any]:
    catalog = []
    settings = {
        (str(item.get("exercise_id")), int(item.get("workout_type", 0))): item
        for item in (state.hidden_exercises or [])
        if isinstance(item, dict)
    }
    exercises = db.scalars(
        select(StrengthExercise).where(StrengthExercise.active.is_(True)).order_by(StrengthExercise.sort_order, StrengthExercise.name)
    ).all()
    for exercise in exercises:
        allowed_types = exercise.metadata_json.get("workout_types", [1, 2, 3])
        if workout_type not in allowed_types:
            continue
        own = settings.get((exercise.code, workout_type), {})
        catalog.append({
            "user_id": str(user_id),
            "workout_type": workout_type,
            "exercise_id": exercise.code,
            "exercise_name": exercise.name,
            "active": own.get("active", True),
            "sort_order": own.get("sort_order", exercise.sort_order),
            "source": exercise.metadata_json.get("source", "catalog"),
        })
    catalog.sort(key=lambda item: int(item.get("sort_order") or 0))

    sessions, session_exercises, sets = [], [], []
    own_workouts = [w for w in (state.workouts or []) if int(w.get("workout_type", 0)) == workout_type]
    own_workouts.sort(key=lambda item: int(item.get("session_number") or 0))
    for workout in own_workouts:
        session_id = str(workout.get("session_id") or workout.get("id"))
        number = int(workout.get("session_number") or 0)
        sessions.append({
            "session_id": session_id, "user_id": str(user_id), "workout_type": workout_type,
            "session_number": number, "date": workout.get("date", ""), "status": workout.get("status", "planned"),
            "legacy_group": workout.get("legacy_group", ""), "source": workout.get("source", "app"),
            "created_at": workout.get("created_at", ""), "updated_at": workout.get("updated_at", ""),
        })
        for ex_index, exercise in enumerate(workout.get("exercises", []), 1):
            session_exercises.append({
                "session_id": session_id, "user_id": str(user_id), "workout_type": workout_type,
                "session_number": number, "exercise_id": exercise.get("exercise_id"),
                "exercise_name": exercise.get("exercise_name", ""),
                "sort_order": exercise.get("sort_order", ex_index), "note": exercise.get("note", ""),
                "source": exercise.get("source", "app"),
            })
            for set_index, item in enumerate(exercise.get("sets", []), 1):
                sets.append({
                    "session_id": session_id, "user_id": str(user_id), "workout_type": workout_type,
                    "session_number": number, "exercise_id": exercise.get("exercise_id"),
                    "exercise_name": exercise.get("exercise_name", ""), "set_number": item.get("set_number", set_index),
                    **{key: item.get(key, "") for key in (
                        "plan_weight", "plan_reps", "fact_weight", "fact_reps", "rpe",
                        "plan_weight_raw", "plan_reps_raw", "fact_weight_raw", "fact_reps_raw", "rpe_raw")},
                    "source": item.get("source", "app"),
                })
    types = [{"user_id": str(user_id), **item} for item in (state.workout_types or [])]
    return {"workout_types": types, "exercise_catalog": catalog, "sessions": sessions, "session_exercises": session_exercises, "sets": sets}


@router.api_route("/api/apps/strength", methods=["GET", "POST"])
async def strength_legacy(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        if request.method == "GET":
            body = dict(request.query_params)
        else:
            body = json.loads((await request.body()).decode("utf-8"))
        action = str(body.get("action") or "ping")
        if action == "ping":
            return JSONResponse({"ok": True, "service": "strength-training"})
        user = resolve_user_for_resource(db, body.get("email"), "strength")
        state = db.scalar(select(StrengthState).where(StrengthState.user_id == user.id))
        if not state:
            state = empty_strength_state(user.id)
            db.add(state)
            db.flush()
        user_payload = {"user_id": str(user.id), "email": normalize_email(body.get("email")), "display_name": user.display_name or "", "status": user.status}
        if action == "openUser":
            payload = {"ok": True, "user": user_payload}
        elif action == "getWorkout":
            payload = {"ok": True, "user": user_payload, "workout": strength_payload(db, state, user.id, int(body.get("type") or 1))}
        elif action == "saveSession":
            workout_type = int(body.get("workout_type") or 0)
            session = body.get("session") or {}
            workouts = list(state.workouts or [])
            own_numbers = [int(w.get("session_number") or 0) for w in workouts if int(w.get("workout_type") or 0) == workout_type]
            number = int(session.get("session_number") or 0) or (max(own_numbers, default=0) + 1)
            session_id = str(session.get("session_id") or f"{user.id}_t{workout_type}_s{number:02d}")
            now = datetime.now(timezone.utc).isoformat()
            item = {**session, "session_id": session_id, "workout_type": workout_type, "session_number": number, "updated_at": now, "created_at": session.get("created_at") or now, "source": "app"}
            item["status"] = "filled" if any(
                set_item.get("rpe") not in (None, "")
                for exercise in item.get("exercises", []) for set_item in exercise.get("sets", [])
            ) else "planned"
            workouts = [w for w in workouts if str(w.get("session_id")) != session_id]
            workouts.append(item)
            state.workouts = workouts
            state.version += 1
            payload = {"ok": True, "session": item, "version": state.version}
        elif action == "saveExerciseSettings":
            workout_type = int(body.get("workout_type") or 0)
            settings = [item for item in (state.hidden_exercises or []) if int(item.get("workout_type", 0)) != workout_type]
            settings.extend({**item, "workout_type": workout_type} for item in (body.get("exercises") or []))
            state.hidden_exercises = settings
            state.version += 1
            payload = {"ok": True, "version": state.version}
        elif action == "getStats":
            workout_type = int(body.get("type") or 1)
            exercise_id = str(body.get("exercise_id") or "")
            history = []
            for workout in sorted(state.workouts or [], key=lambda w: str(w.get("date") or "")):
                if int(workout.get("workout_type") or 0) != workout_type or not workout.get("date"):
                    continue
                exercise = next((x for x in workout.get("exercises", []) if str(x.get("exercise_id")) == exercise_id), None)
                candidates = []
                for set_item in (exercise or {}).get("sets", [])[1:]:
                    try:
                        weight, reps, rpe = float(set_item["fact_weight"]), float(set_item["fact_reps"]), float(set_item["rpe"])
                        estimate = weight * (1 + (reps + max(0, 10 - rpe)) / 30) / (1 + 8 / 30)
                        candidates.append((weight, estimate, set_item))
                    except (KeyError, TypeError, ValueError):
                        pass
                if candidates:
                    best = sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[0]
                    history.append({"session_id": workout.get("session_id"), "session_number": workout.get("session_number"), "date": workout.get("date"), "estimated_8rm": round(best[1], 2), "source_set": best[2].get("set_number"), "source_weight": best[0], "source_reps": best[2].get("fact_reps"), "source_rpe": best[2].get("rpe")})
            payload = {"ok": True, "user": user_payload, "stats": history}
        else:
            payload = error("Unknown action: " + action)
        db.commit()
        return JSONResponse(payload)
    except (AppAccessError, ValueError, TypeError, json.JSONDecodeError) as exc:
        db.rollback()
        return JSONResponse(error(str(exc)))


@router.get("/api/apps/metabolism")
def metabolism_get(email: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        user = resolve_user_for_resource(db, email, "metabolism")
        state = db.scalar(select(MetabolismState).where(MetabolismState.user_id == user.id))
        if not state:
            state = MetabolismState(user_id=user.id, variants={}, source="app")
            db.add(state)
            db.commit()
            db.refresh(state)
        return {"ok": True, "email": normalize_email(email), "variants": state.variants, "activeVariant": state.active_variant, "version": state.version}
    except AppAccessError as exc:
        return error(str(exc))


@router.put("/api/apps/metabolism")
async def metabolism_put(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        body = await request.json()
        user = resolve_user_for_resource(db, body.get("email"), "metabolism")
        state = db.scalar(select(MetabolismState).where(MetabolismState.user_id == user.id))
        if not state:
            state = MetabolismState(user_id=user.id, variants={}, source="app")
            db.add(state)
            db.flush()
        expected = body.get("version")
        if expected is not None and int(expected) != state.version:
            return JSONResponse(error("STATE_VERSION_CONFLICT"), status_code=409)
        variants = body.get("variants")
        active = int(body.get("activeVariant") or 1)
        if not isinstance(variants, dict) or active not in (1, 2):
            raise ValueError("INVALID_STATE")
        state.variants = variants
        state.active_variant = active
        state.version += 1
        db.commit()
        return JSONResponse({"ok": True, "version": state.version})
    except (AppAccessError, ValueError, TypeError) as exc:
        db.rollback()
        return JSONResponse(error(str(exc)), status_code=400)


@router.get("/admin/api/apps/users")
def admin_app_users(
    app_code: str = Query(pattern="^(dqs|strength|metabolism)$"),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    model = {"dqs": DqsState, "strength": StrengthState, "metabolism": MetabolismState}[app_code]
    states = db.scalars(select(model).order_by(model.updated_at.desc())).all()
    return {"ok": True, "users": [{"user_id": str(item.user_id), "email": primary_email(db, item.user_id), "version": item.version, "updated_at": utc_iso(item.updated_at)} for item in states]}
