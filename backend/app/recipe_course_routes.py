from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.account_auth_routes import require_native_user
from app.access_service import course_start_is_open
from app.app_service import AppAccessError, require_user_resource
from app.database import get_db
from app.models import CourseStepProgress, User
from app.recipe_course_service import COURSE_CODE, RESOURCE_CODE, course_manifest, course_material

router = APIRouter(prefix="/api/recipes/course", tags=["recipe-course"])


class CourseAction(BaseModel):
    email: str = ""
    timezone_name: str | None = None


def resolve_course_user(request: Request, db: Session) -> User:
    try:
        user = require_user_resource(db, require_native_user(request, db), RESOURCE_CODE)
    except AppAccessError as exc:
        raise HTTPException(403, str(exc)) from exc
    if not course_start_is_open(db, user.id, RESOURCE_CODE):
        raise HTTPException(403, "Курс пока закрыт по условиям доступа")
    return user


def course_payload(db: Session, user: User, manifest: dict) -> dict:
    completed = {(row.stage_number, row.step_index) for row in db.scalars(
        select(CourseStepProgress).where(CourseStepProgress.user_id == user.id,
                                        CourseStepProgress.course_code == COURSE_CODE)
    )}
    groups = []
    for group in manifest["days"]:
        number = group["number"]
        readable = [i for i, step in enumerate(group["steps"]) if not step["locked"]]
        done = [i for i in readable if (number, i) in completed]
        groups.append({
            "number": number, "opened": True, "can_open": True, "locked_reason": None,
            "unlock_at": None, "first_opened_at": None, "next_day_unlock_at": None,
            "steps_total": len(group["steps"]), "required_steps_total": len(readable),
            "completed_steps": done, "next_step": next((i for i in readable if i not in done), None),
            "task_unlocked": False, "task_opened": False, "checkmarks": {}, "check_count": 0,
            "completed": bool(readable) and len(done) == len(readable), "completed_at": None,
            "offer": None, "app": None,
        })
    return {"ok": True, "course_version": manifest["courseVersion"],
            "server_now": datetime.now(timezone.utc).isoformat(), "fully_unlocked": True,
            "current_day": 1, "days": groups}


@router.get("/manifest")
def manifest(request: Request, db: Session = Depends(get_db)) -> dict:
    resolve_course_user(request, db)
    return course_manifest(db)


@router.get("/materials")
def material(request: Request, step_id: str, db: Session = Depends(get_db)) -> dict:
    resolve_course_user(request, db)
    result = course_material(db, course_manifest(db), step_id)
    if not result["materials"]:
        raise HTTPException(404, "Материал курса пока недоступен")
    return result


@router.get("")
def state(request: Request, db: Session = Depends(get_db)) -> dict:
    user = resolve_course_user(request, db)
    return course_payload(db, user, course_manifest(db))


@router.post("/days/{group}/open")
def open_group(group: int, body: CourseAction, request: Request, db: Session = Depends(get_db)) -> dict:
    user = resolve_course_user(request, db)
    manifest = course_manifest(db)
    if not 1 <= group <= len(manifest["days"]):
        raise HTTPException(404, "Раздел не найден")
    return course_payload(db, user, manifest)


@router.post("/days/{group}/steps/{index}/complete")
def complete_step(group: int, index: int, body: CourseAction, request: Request,
                  db: Session = Depends(get_db)) -> dict:
    user = resolve_course_user(request, db)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    manifest = course_manifest(db)
    steps = manifest["days"][group - 1]["steps"] if 1 <= group <= len(manifest["days"]) else []
    if not 0 <= index < len(steps) or steps[index]["locked"]:
        raise HTTPException(404, "Материал курса пока недоступен")
    existing = db.scalar(select(CourseStepProgress).where(
        CourseStepProgress.user_id == user.id, CourseStepProgress.course_code == COURSE_CODE,
        CourseStepProgress.stage_number == group, CourseStepProgress.step_index == index,
    ))
    if existing is None:
        db.add(CourseStepProgress(user_id=user.id, course_code=COURSE_CODE,
                                 stage_number=group, step_index=index, step_kind="article"))
    db.commit()
    # Эти отметки не завершают дни МК и не запускают его события и рассылки.
    return course_payload(db, user, manifest)
