"""Transaction locks protect stable course IDs while positional progress is used."""
from fastapi import HTTPException
from sqlalchemy import text
from pydantic import BaseModel, Field

KEYS = {"masterclass-21": 694128101, "calories": 694128102}


class StructureAction(BaseModel):
    structure_version: int | None = Field(default=None, ge=1)
    step_id: str | None = Field(default=None, min_length=1, max_length=160)


def lock_course(db, course_code: str, *, exclusive: bool = False):
    key = KEYS.get(course_code)
    if key is None:
        raise HTTPException(404, "Курс не найден")
    if db.get_bind().dialect.name == "postgresql":
        function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
        db.execute(text(f"SELECT {function}(:key)"), {"key": key})


def check_structure(manifest: dict, version: int, body, *, step: dict | None = None):
    if manifest.get("minimum_required_structure_revision"):
        if body.structure_version != version or (step is not None and body.step_id != step["id"]):
            raise HTTPException(409, detail={"reason": "structure_changed", "structure_version": version})
