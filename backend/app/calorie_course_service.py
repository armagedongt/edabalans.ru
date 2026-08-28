from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.course_structure_service import sanitize_fragment, validate_url
from app.managed_documents import ensure_seed_document, publish_document
from app.models import CourseStageProgress, ManagedDocumentVersion
from app.product_catalog_service import product_public


DOCUMENT_TYPE = "course-structure"
DOCUMENT_KEY = "calories"
MANAGED_SCHEMA_VERSION = 1
COURSE_CONTENT_ROOT = Path(__file__).resolve().parents[2] / "content" / "calories"
COURSE_MANIFEST_PATH = COURSE_CONTENT_ROOT / "course" / "course.json"
COURSE_EDITABLE = {"launchReady"}
STAGE_EDITABLE = {
    "title",
    "tocSummary",
    "lead",
    "media",
    "videoId",
    "image",
    "timings",
    "intro",
    "afterLead",
    "afterTitle",
    "afterText",
}
STEP_EDITABLE = {"title", "summary", "hidden"}
HTML_FIELDS = {"intro", "afterLead", "afterText"}


def check_id(stage: int, index: int) -> str:
    return f"stage-{stage}-check-{index + 1}"


def normalize_seed(manifest: dict) -> dict:
    result = deepcopy(manifest)
    result.setdefault("launchReady", False)
    stages = result.get("stages", result.get("days", []))
    result["stages"] = stages
    result["days"] = stages
    for stage in stages:
        number = int(stage["number"])
        stage.setdefault("media", "none")
        stage.setdefault("videoId", None)
        stage.setdefault("image", None)
        stage.setdefault("timings", [])
        stage.setdefault("intro", "")
        stage.setdefault("afterLead", "")
        stage.setdefault("afterTitle", "")
        stage.setdefault("afterText", "")
        stage["checks"] = [
            item
            if isinstance(item, dict)
            else {
                "id": check_id(number, index),
                "text": str(item),
                "required": True,
                "hidden": False,
            }
            for index, item in enumerate(stage.get("checks", []))
        ]
        for step in stage.get("steps", []):
            step.setdefault("required", True)
            step.setdefault("hidden", False)
    return result

def seed_manifest() -> dict:
    return normalize_seed(json.loads(COURSE_MANIFEST_PATH.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class CalorieCourseContext:
    revision: ManagedDocumentVersion
    manifest: dict
    stages: dict[int, dict]
    last_stage: int
    checks: dict[int, list[dict]]


def active_course_version(db: Session) -> ManagedDocumentVersion:
    return ensure_seed_document(
        db,
        document_type=DOCUMENT_TYPE,
        document_key=DOCUMENT_KEY,
        schema_version=MANAGED_SCHEMA_VERSION,
        payload=seed_manifest(),
    )


def runtime_manifest(payload: dict) -> dict:
    return normalize_seed(payload)


def course_context(db: Session) -> CalorieCourseContext:
    revision = active_course_version(db)
    manifest = runtime_manifest(revision.payload)
    manifest["title"] = product_public(db, "calories")["name"]
    stages = {int(stage["number"]): stage for stage in manifest["stages"]}
    return CalorieCourseContext(
        revision=revision,
        manifest=manifest,
        stages=stages,
        last_stage=max(stages),
        checks={number: list(stage.get("checks", [])) for number, stage in stages.items()},
    )


def serialize_version(
    version: ManagedDocumentVersion, *, include_payload: bool = True
) -> dict:
    result = {
        "id": str(version.id),
        "version": version.version_no,
        "created_at": version.created_at.isoformat(),
        "created_by": version.created_by,
        "active": version.is_active,
    }
    if include_payload:
        result["manifest"] = deepcopy(version.payload)
    return result


def normalize_editor_payload(proposed: dict, current: dict, next_version: int) -> dict:
    if not isinstance(proposed, dict):
        raise HTTPException(422, "Структура должна быть объектом")
    if len(json.dumps(proposed, ensure_ascii=False).encode("utf-8")) > 2_000_000:
        raise HTTPException(413, "Структура превышает допустимый размер")
    result = normalize_seed(proposed)
    current = normalize_seed(current)
    if result.get("courseCode") != current.get("courseCode"):
        raise HTTPException(422, "Технический код курса нельзя менять")
    stages = result.get("stages")
    current_stages = current.get("stages")
    if (
        not isinstance(stages, list)
        or not stages
        or not all(isinstance(stage, dict) for stage in stages)
        or len(stages) != len(current_stages)
    ):
        raise HTTPException(422, "Добавление и удаление этапов выполняется через чат")
    if [stage.get("number") for stage in stages] != list(range(1, len(stages) + 1)):
        raise HTTPException(422, "Порядок этапов нельзя менять редактором")

    for key in current:
        if key not in COURSE_EDITABLE | {"stages", "days"} and result.get(key) != current.get(key):
            raise HTTPException(422, f"Техническое поле курса нельзя менять: {key}")
    unexpected_course = set(result) - set(current)
    if unexpected_course:
        raise HTTPException(422, f"Неизвестное поле курса: {sorted(unexpected_course)[0]}")
    result["launchReady"] = bool(result.get("launchReady", False))

    global_step_ids: set[str] = set()
    for stage, old_stage in zip(stages, current_stages, strict=True):
        number = int(stage["number"])
        unexpected_stage = set(stage) - set(old_stage) - STAGE_EDITABLE
        if unexpected_stage:
            raise HTTPException(
                422, f"Этап {number}: неизвестное поле {sorted(unexpected_stage)[0]}"
            )
        for key in old_stage:
            if key not in STAGE_EDITABLE | {"steps", "checks"}:
                if stage.get(key) != old_stage.get(key):
                    raise HTTPException(422, f"Этап {number}: поле {key} нельзя менять")
        for key in STAGE_EDITABLE:
            if key not in stage:
                continue
            if isinstance(stage[key], str) and len(stage[key]) > 50_000:
                raise HTTPException(422, f"Этап {number}: поле {key} слишком длинное")
            if key in HTML_FIELDS:
                stage[key] = sanitize_fragment(stage[key])
            elif isinstance(stage[key], str):
                stage[key] = stage[key].strip()
        validate_url(stage.get("image"), image=True)
        validate_url(stage.get("videoId"))

        old_steps = list(old_stage.get("steps", []))
        steps = stage.get("steps")
        if not isinstance(steps, list) or len(steps) != len(old_steps):
            raise HTTPException(422, "Добавление и удаление материалов выполняется через чат")
        old_by_id = {step["id"]: step for step in old_steps}
        if [step.get("id") for step in steps] != [step["id"] for step in old_steps]:
            raise HTTPException(422, f"Этап {number}: порядок материалов нельзя менять")
        for step in steps:
            step_id = str(step.get("id") or "")
            if not step_id or step_id in global_step_ids:
                raise HTTPException(422, f"Повторяется ID материала: {step_id}")
            global_step_ids.add(step_id)
            old = old_by_id[step_id]
            unexpected_step = set(step) - set(old) - STEP_EDITABLE - {
                "requiredForAllAfterRevision"
            }
            if unexpected_step:
                raise HTTPException(
                    422,
                    f"Материал {step_id}: неизвестное поле {sorted(unexpected_step)[0]}",
                )
            for key in old:
                if key not in STEP_EDITABLE | {"requiredForAllAfterRevision"}:
                    if step.get(key) != old.get(key):
                        raise HTTPException(422, f"Материал {step_id}: поле {key} нельзя менять")
            if old.get("hidden", False) and not step.get("hidden", False):
                step["requiredForAllAfterRevision"] = next_version
            elif old.get("requiredForAllAfterRevision") is not None:
                step["requiredForAllAfterRevision"] = old["requiredForAllAfterRevision"]
            for key in ("title", "summary"):
                step[key] = str(step.get(key) or "").strip()
                if not step[key] or len(step[key]) > 5_000:
                    raise HTTPException(422, f"Материал {step_id}: заполните {key}")

        old_checks = {item["id"]: item for item in old_stage.get("checks", [])}
        checks = stage.get("checks")
        if not isinstance(checks, list) or not checks or len(checks) > 200:
            raise HTTPException(422, f"Этап {number}: добавьте хотя бы один пункт задания")
        seen: set[str] = set()
        for item in checks:
            if not isinstance(item, dict):
                raise HTTPException(422, f"Этап {number}: неверный пункт задания")
            if not item.get("id"):
                item["id"] = f"stage-{number}-check-{uuid.uuid4().hex[:12]}"
            item_id = str(item["id"])
            if item_id in seen:
                raise HTTPException(422, f"Этап {number}: повторяется ID пункта")
            seen.add(item_id)
            old = old_checks.get(item_id)
            item["text"] = str(item.get("text") or "").strip()
            if not item["text"] or len(item["text"]) > 5_000:
                raise HTTPException(422, f"Этап {number}: пустой пункт задания")
            item["required"] = old.get("required", True) if old else True
            item["hidden"] = bool(item.get("hidden", False))
            if old and old.get("hidden", False) and not item["hidden"]:
                item["requiredForAllAfterRevision"] = next_version
            elif old and old.get("requiredForAllAfterRevision") is not None:
                item["requiredForAllAfterRevision"] = old["requiredForAllAfterRevision"]
        if set(old_checks) - seen:
            raise HTTPException(422, "Пункты задания нельзя удалять — используйте «Скрыть»")
    result["days"] = result["stages"]
    return result


def publish_course_structure(
    db: Session, *, manifest: dict, expected_version: int, admin: str
) -> ManagedDocumentVersion:
    current = active_course_version(db)
    prepared = normalize_editor_payload(manifest, current.payload, expected_version + 1)
    return publish_document(
        db,
        document_type=DOCUMENT_TYPE,
        document_key=DOCUMENT_KEY,
        schema_version=MANAGED_SCHEMA_VERSION,
        payload=prepared,
        expected_version=expected_version,
        admin=admin,
    )


def prepare_restore_payload(source: dict, current: dict, next_version: int) -> dict:
    return normalize_editor_payload(deepcopy(source), current, next_version)


def effective_required_step_ids(
    context: CalorieCourseContext, progress: CourseStageProgress, stage: int
) -> list[str]:
    baseline = set(progress.required_step_ids or [])
    result: list[str] = []
    for step in context.stages[stage].get("steps", []):
        if step.get("hidden", False) or not step.get("required", True):
            continue
        reactivated = int(step.get("requiredForAllAfterRevision") or 0)
        if step["id"] in baseline or reactivated > progress.structure_revision_no:
            result.append(step["id"])
    return result


def effective_required_check_ids(
    context: CalorieCourseContext, progress: CourseStageProgress, stage: int
) -> list[str]:
    baseline = set(progress.required_check_ids or [])
    result: list[str] = []
    for item in context.checks[stage]:
        if item.get("hidden", False) or not item.get("required", True):
            continue
        reactivated = int(item.get("requiredForAllAfterRevision") or 0)
        if item["id"] in baseline or reactivated > progress.structure_revision_no:
            result.append(item["id"])
    return result
