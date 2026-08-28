from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.app_service import AppAccessError, resolve_user_for_resource
from app.calorie_course_material_service import publication_status, published_materials
from app.calorie_course_service import (
    DOCUMENT_KEY,
    CalorieCourseContext,
    course_context,
    effective_required_check_ids,
    effective_required_step_ids,
)
from app.database import get_db
from app.models import CourseEvent, CourseStageProgress, CourseStepProgress, User


router = APIRouter(prefix="/api/calories", tags=["calorie-course"])
RESOURCE_CODE = "ACCESS_CALORIES"


class RunActionIn(BaseModel):
    email: str
    timezone_name: str | None = None


class CourseCheckIn(BaseModel):
    email: str
    checked: bool


def aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def resolve_course_user(request: Request, db: Session, email: str) -> User:
    # The current Tilda Members Area remains the only interactive login. This
    # mirrors the Masterclass boundary and does not create a second sign-in.
    try:
        user = resolve_user_for_resource(db, email, RESOURCE_CODE)
    except AppAccessError as exc:
        raise HTTPException(403, str(exc)) from exc
    if not publication_status(db)["ready"]:
        raise HTTPException(409, detail={"reason": "course_preparing"})
    return user


def course_event(
    db: Session,
    user_id: uuid.UUID,
    event_key: str,
    event_type: str,
    *,
    details: dict[str, Any] | None = None,
) -> CourseEvent:
    event = db.scalar(
        select(CourseEvent).where(
            CourseEvent.user_id == user_id,
            CourseEvent.course_code == DOCUMENT_KEY,
            CourseEvent.event_key == event_key,
        )
    )
    if event is None:
        event = CourseEvent(
            user_id=user_id,
            course_code=DOCUMENT_KEY,
            event_key=event_key,
            event_type=event_type,
            details=details or {},
        )
        db.add(event)
        db.flush()
    return event


def stage_progress(
    db: Session, user_id: uuid.UUID, stage: int
) -> CourseStageProgress | None:
    return db.scalar(
        select(CourseStageProgress).where(
            CourseStageProgress.user_id == user_id,
            CourseStageProgress.course_code == DOCUMENT_KEY,
            CourseStageProgress.stage_number == stage,
        )
    )


def current_required_step_ids(context: CalorieCourseContext, stage: int) -> list[str]:
    if stage not in context.stages:
        raise HTTPException(404, "Этап курса не найден")
    return [
        step["id"]
        for step in context.stages[stage].get("steps", [])
        if not step.get("hidden", False) and step.get("required", True)
    ]


def current_required_check_ids(context: CalorieCourseContext, stage: int) -> list[str]:
    return [
        item["id"]
        for item in context.checks[stage]
        if not item.get("hidden", False) and item.get("required", True)
    ]


def completed_step_indexes(db: Session, user_id: uuid.UUID, stage: int) -> set[int]:
    return set(
        db.scalars(
            select(CourseStepProgress.step_index).where(
                CourseStepProgress.user_id == user_id,
                CourseStepProgress.course_code == DOCUMENT_KEY,
                CourseStepProgress.stage_number == stage,
            )
        )
    )


def required_step_indexes(
    context: CalorieCourseContext, progress: CourseStageProgress, stage: int
) -> list[int]:
    required_ids = set(effective_required_step_ids(context, progress, stage))
    return [
        index
        for index, step in enumerate(context.stages[stage].get("steps", []))
        if step["id"] in required_ids
    ]


def stage_can_open(
    db: Session, user_id: uuid.UUID, stage: int, context: CalorieCourseContext
) -> tuple[bool, str | None]:
    if stage == 1:
        return True, None
    if stage not in context.stages:
        return False, "stage_not_found"
    previous = stage_progress(db, user_id, stage - 1)
    if previous is None:
        return False, "previous_stage_not_opened"
    if previous.completed_at is None:
        return False, "previous_stage_not_completed"
    return True, None


def open_stage(
    db: Session,
    user: User,
    context: CalorieCourseContext,
    stage: int,
    now: datetime,
) -> CourseStageProgress:
    if stage not in context.stages:
        raise HTTPException(404, "Этап курса не найден")
    existing = stage_progress(db, user.id, stage)
    if existing is not None:
        return existing
    allowed, reason = stage_can_open(db, user.id, stage, context)
    if not allowed:
        raise HTTPException(409, detail={"reason": reason})
    progress = CourseStageProgress(
        user_id=user.id,
        course_code=DOCUMENT_KEY,
        stage_number=stage,
        first_opened_at=now,
        structure_revision_no=context.revision.version_no,
        required_step_ids=current_required_step_ids(context, stage),
        required_check_ids=current_required_check_ids(context, stage),
        checkmarks={},
    )
    db.add(progress)
    db.flush()
    course_event(
        db,
        user.id,
        f"stage:{stage}:opened",
        "calories_stage_opened",
        details={"stage": stage, "stage_title": context.stages[stage]["title"]},
    )
    return progress


def finalize_stage(
    db: Session,
    user: User,
    progress: CourseStageProgress,
    stage: int,
    context: CalorieCourseContext,
    now: datetime,
) -> None:
    if progress.completed_at is not None:
        return
    progress.completed_at = now
    course_event(
        db,
        user.id,
        f"stage:{stage}:completed",
        "calories_stage_completed",
        details={"stage": stage, "stage_title": context.stages[stage]["title"]},
    )
    if stage == context.last_stage:
        course_event(
            db,
            user.id,
            "course:completed",
            "calories_course_completed",
            details={"stage": stage},
        )


def course_payload(
    db: Session, user: User, now: datetime, context: CalorieCourseContext | None = None
) -> dict:
    context = context or course_context(db)
    progress_rows = {
        row.stage_number: row
        for row in db.scalars(
            select(CourseStageProgress).where(
                CourseStageProgress.user_id == user.id,
                CourseStageProgress.course_code == DOCUMENT_KEY,
            )
        )
    }
    step_rows: dict[int, set[int]] = {
        stage: set() for stage in range(1, context.last_stage + 1)
    }
    for row in db.scalars(
        select(CourseStepProgress).where(
            CourseStepProgress.user_id == user.id,
            CourseStepProgress.course_code == DOCUMENT_KEY,
        )
    ):
        if row.stage_number in step_rows:
            step_rows[row.stage_number].add(row.step_index)

    stages = []
    for stage in range(1, context.last_stage + 1):
        progress = progress_rows.get(stage)
        can_open, reason = stage_can_open(db, user.id, stage, context)
        steps = context.stages[stage].get("steps", [])
        completed_indexes = step_rows[stage]
        required_ids = (
            effective_required_step_ids(context, progress, stage)
            if progress
            else current_required_step_ids(context, stage)
        )
        required_set = set(required_ids)
        required_indexes = [
            index for index, step in enumerate(steps) if step["id"] in required_set
        ]
        checkmarks = {}
        if progress:
            stored = dict(progress.checkmarks or {})
            checkmarks = {
                str(index): stored.get(item["id"]) is True
                for index, item in enumerate(context.checks[stage])
            }
        stages.append(
            {
                "number": stage,
                "opened": progress is not None,
                "can_open": progress is not None or can_open,
                "locked_reason": None if progress or can_open else reason,
                "unlock_at": None,
                "first_opened_at": (
                    aware_utc(progress.first_opened_at).isoformat() if progress else None
                ),
                "timezone_name": None,
                "next_day_unlock_at": (
                    aware_utc(progress.completed_at).isoformat()
                    if progress and progress.completed_at
                    else None
                ),
                "steps_total": len([step for step in steps if not step.get("hidden", False)]),
                "required_steps_total": len(required_ids),
                "completed_steps": sorted(completed_indexes),
                "next_step": next(
                    (
                        index
                        for index, step in enumerate(steps)
                        if step["id"] in required_set and index not in completed_indexes
                    ),
                    None,
                ),
                "task_unlocked": all(index in completed_indexes for index in required_indexes),
                "task_opened": bool(progress and progress.task_opened_at),
                "checkmarks": checkmarks,
                "check_count": len(context.checks[stage]),
                "completed": bool(progress and progress.completed_at),
                "completed_at": (
                    aware_utc(progress.completed_at).isoformat()
                    if progress and progress.completed_at
                    else None
                ),
                "offer": None,
                "app": None,
            }
        )
    return {
        "ok": True,
        "course_version": context.manifest["courseVersion"],
        "structure_version": context.revision.version_no,
        "server_now": now.isoformat(),
        "unlock_schedule": "next_stage_after_completion",
        "accelerated_test": False,
        "fully_unlocked": False,
        "current_day": max(progress_rows) if progress_rows else 1,
        "days": stages,
        "stages": stages,
    }


@router.get("/course/manifest")
def course_manifest(
    email: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    resolve_course_user(request, db, email)
    return course_context(db).manifest


@router.get("/course/materials")
def course_materials(
    email: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = resolve_course_user(request, db, email)
    state = course_payload(db, user, datetime.now(timezone.utc))
    allowed = {
        int(stage["number"])
        for stage in state["stages"]
        if stage["opened"] or stage["can_open"]
    }
    return published_materials(db, allowed_stages=allowed)


@router.get("/course")
def course_state(
    email: str,
    request: Request,
    timezone_name: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    user = resolve_course_user(request, db, email)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(timezone.utc)
    context = course_context(db)
    open_stage(db, user, context, 1, now)
    course_event(
        db,
        user.id,
        "course:opened",
        "calories_course_opened",
        details={"program_stages": context.last_stage},
    )
    db.commit()
    return course_payload(db, user, now, context)
@router.post("/course/days/{stage}/open")
def course_open_stage(
    stage: int,
    body: RunActionIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = resolve_course_user(request, db, body.email)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(timezone.utc)
    context = course_context(db)
    open_stage(db, user, context, stage, now)
    db.commit()
    return course_payload(db, user, now, context)


@router.post("/course/days/{stage}/steps/{index}/complete")
def course_complete_step(
    stage: int,
    index: int,
    body: RunActionIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = resolve_course_user(request, db, body.email)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(timezone.utc)
    context = course_context(db)
    progress = stage_progress(db, user.id, stage)
    if progress is None:
        raise HTTPException(409, detail={"reason": "stage_not_opened"})
    steps = context.stages.get(stage, {}).get("steps", [])
    if index < 0 or index >= len(steps) or steps[index].get("hidden", False):
        raise HTTPException(404, "Материал курса не найден")
    completed = completed_step_indexes(db, user.id, stage)
    if index in completed:
        return course_payload(db, user, now, context)
    required_ids = set(effective_required_step_ids(context, progress, stage))
    required_before = [
        previous_index
        for previous_index, previous in enumerate(steps[:index])
        if previous["id"] in required_ids
    ]
    if any(previous not in completed for previous in required_before):
        raise HTTPException(409, detail={"reason": "previous_step_not_completed"})
    step = steps[index]
    db.add(
        CourseStepProgress(
            user_id=user.id,
            course_code=DOCUMENT_KEY,
            stage_number=stage,
            step_index=index,
            step_kind=step["kind"],
            completed_at=now,
        )
    )
    course_event(
        db,
        user.id,
        f"stage:{stage}:step:{index}:completed",
        "calories_material_completed",
        details={
            "stage": stage,
            "step_index": index,
            "step_id": step["id"],
            "step_kind": step["kind"],
        },
    )
    db.commit()
    return course_payload(db, user, now, context)


@router.post("/course/days/{stage}/task/open")
def course_open_task(
    stage: int,
    body: RunActionIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = resolve_course_user(request, db, body.email)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(timezone.utc)
    context = course_context(db)
    progress = stage_progress(db, user.id, stage)
    if progress is None:
        raise HTTPException(409, detail={"reason": "stage_not_opened"})
    completed = completed_step_indexes(db, user.id, stage)
    if any(
        step_index not in completed
        for step_index in required_step_indexes(context, progress, stage)
    ):
        raise HTTPException(409, detail={"reason": "materials_not_completed"})
    if progress.task_opened_at is None:
        progress.task_opened_at = now
        course_event(
            db,
            user.id,
            f"stage:{stage}:task:opened",
            "calories_stage_assignment_opened",
            details={"stage": stage},
        )
    db.commit()
    return course_payload(db, user, now, context)


@router.put("/course/days/{stage}/checks/{index}")
def course_update_check(
    stage: int,
    index: int,
    body: CourseCheckIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = resolve_course_user(request, db, body.email)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(timezone.utc)
    context = course_context(db)
    progress = stage_progress(db, user.id, stage)
    if progress is None or progress.task_opened_at is None:
        raise HTTPException(409, detail={"reason": "task_not_opened"})
    checks = context.checks.get(stage, [])
    if index < 0 or index >= len(checks) or checks[index].get("hidden", False):
        raise HTTPException(404, "Пункт задания не найден")
    checkmarks = dict(progress.checkmarks or {})
    checkmarks[checks[index]["id"]] = body.checked
    progress.checkmarks = checkmarks
    if all(
        checkmarks.get(item_id) is True
        for item_id in effective_required_check_ids(context, progress, stage)
    ):
        finalize_stage(db, user, progress, stage, context, now)
    db.commit()
    return course_payload(db, user, now, context)
