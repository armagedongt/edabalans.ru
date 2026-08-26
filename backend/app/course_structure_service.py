from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import uuid
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.managed_documents import ensure_seed_document, publish_document
from app.models import ManagedDocumentVersion, MasterclassDayProgress
from app.product_catalog_service import product_public


DOCUMENT_TYPE = "course-structure"
DOCUMENT_KEY = "masterclass-21"
MANAGED_SCHEMA_VERSION = 1
COURSE_CONTENT_ROOT = Path(__file__).resolve().parents[2] / "content" / "masterclass"
COURSE_MANIFEST_PATH = COURSE_CONTENT_ROOT / "course" / "course.json"
SYSTEM_KINDS = {
    "questionnaire", "messenger", "offer", "dqs", "recipes-part-1",
    "recipes-part-2", "closing-review",
}
STEP_EDITABLE = {"title", "label", "summary", "hidden"}
DAY_EDITABLE = {
    "title", "tocSummary", "lead", "media", "videoId", "image", "intro",
    "afterLead", "afterTitle", "afterText",
}
HTML_FIELDS = {"intro", "afterLead", "afterText"}
REMOVED_DAY_FIELDS = {
    "kicker", "shortTitle", "assignmentTitle", "assignmentLead",
    "assignmentText", "nextTitle", "nextTeaser",
}
SAFE_ASSET = re.compile(r"^[A-Za-z0-9А-Яа-яЁё._ -]+\.(md|txt|json)$")
SAFE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{4,120}$")


class FragmentSanitizer(HTMLParser):
    allowed = {"strong", "em", "a", "br"}
    blocked = {"script", "style", "iframe", "object", "svg", "math"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.blocked:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in self.allowed:
            return
        rendered = ""
        if tag == "a":
            href = next((value for name, value in attrs if name.lower() == "href"), None)
            parsed = urlparse((href or "").strip())
            if href and (href == "#" or parsed.scheme in {"http", "https"}):
                rendered += f' href="{escape(href, quote=True)}"'
            if any(name.lower() == "data-dqs-tutorial-link" for name, _ in attrs):
                rendered += " data-dqs-tutorial-link"
        self.parts.append(f"<{tag}{rendered}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.blocked:
            self.blocked_depth = max(0, self.blocked_depth - 1)
        elif not self.blocked_depth and tag in self.allowed and tag != "br":
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.parts.append(escape(data))


def sanitize_fragment(value: object) -> str:
    parser = FragmentSanitizer()
    parser.feed(str(value or ""))
    parser.close()
    return "".join(parser.parts).strip()


def seed_manifest() -> dict:
    return normalize_seed(json.loads(COURSE_MANIFEST_PATH.read_text(encoding="utf-8")))


def check_id(day: int, index: int) -> str:
    return f"day-{day}-check-{index + 1}"


def normalize_seed(manifest: dict) -> dict:
    result = deepcopy(manifest)
    for day in result.get("days", []):
        if not day.get("afterLead") and day.get("assignmentLead"):
            day["afterLead"] = day["assignmentLead"]
        if not day.get("afterText") and day.get("assignmentText"):
            day["afterText"] = day["assignmentText"]
        for key in REMOVED_DAY_FIELDS:
            day.pop(key, None)
        day.setdefault("afterLead", "")
        day_number = int(day["number"])
        day["checks"] = [
            item if isinstance(item, dict) else {
                "id": check_id(day_number, index),
                "text": str(item),
                "required": True,
                "hidden": False,
            }
            for index, item in enumerate(day.get("checks", []))
        ]
        for step in day.get("steps", []):
            step.setdefault("hidden", False)
            step.pop("shortTitle", None)
            if step.get("contentKind") == "imported":
                step.setdefault("contentPageTitle", step.get("title"))
    return result


@dataclass(frozen=True)
class CourseContext:
    revision: ManagedDocumentVersion
    manifest: dict
    days: dict[int, dict]
    last_day: int
    checks: dict[int, list[dict]]
    apps: dict[int, str]
    offers: dict[int, tuple[str, str]]
    content_files: dict[str, Path]


def active_course_version(db: Session) -> ManagedDocumentVersion:
    return ensure_seed_document(
        db,
        document_type=DOCUMENT_TYPE,
        document_key=DOCUMENT_KEY,
        schema_version=MANAGED_SCHEMA_VERSION,
        payload=seed_manifest(),
    )


def runtime_manifest(payload: dict) -> dict:
    # Hidden entries stay in their original positions so legacy positional progress
    # keeps its meaning. The client omits them visually and the server excludes them
    # from required checks.
    return normalize_seed(payload)


def course_context(db: Session) -> CourseContext:
    revision = active_course_version(db)
    manifest = runtime_manifest(revision.payload)
    manifest["title"] = product_public(db, "masterclass")["name"]
    days = {int(day["number"]): day for day in manifest["days"]}
    content_files = {
        "extracted-2026-08-23.json": (
            COURSE_CONTENT_ROOT / "imported-draft" / "extracted-2026-08-23.json"
        )
    }
    for day in manifest["days"]:
        for step in day.get("steps", []):
            if step.get("hidden", False):
                continue
            asset = step.get("contentAsset")
            if asset:
                content_files.setdefault(asset, COURSE_CONTENT_ROOT / "source-current" / asset)
    return CourseContext(
        revision=revision,
        manifest=manifest,
        days=days,
        last_day=max(days),
        checks={number: list(day.get("checks", [])) for number, day in days.items()},
        apps={
            number: step["kind"]
            for number, day in days.items()
            for step in day.get("steps", [])
            if not step.get("hidden", False)
            and step["kind"] in {"dqs", "recipes-part-1", "recipes-part-2", "closing-review"}
        },
        offers={
            number: (step["placement"], step["event"])
            for number, day in days.items()
            for step in day.get("steps", [])
            if not step.get("hidden", False) and step["kind"] == "offer"
        },
        content_files=content_files,
    )


def serialize_version(version: ManagedDocumentVersion, *, include_payload: bool = True) -> dict:
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


def validate_url(value: object, *, image: bool = False) -> None:
    if value in (None, ""):
        return
    text = str(value).strip()
    if re.search(r'''[\s<>"'\\()]''', text):
        raise HTTPException(422, f"Недопустимые символы в ссылке: {text[:120]}")
    if not image and SAFE_VIDEO_ID.fullmatch(text):
        return
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(422, f"Недопустимая ссылка: {text[:120]}")


def normalize_editor_payload(proposed: dict, current: dict, next_version: int) -> dict:
    if not isinstance(proposed, dict):
        raise HTTPException(422, "Структура должна быть объектом")
    if len(json.dumps(proposed, ensure_ascii=False).encode("utf-8")) > 2_000_000:
        raise HTTPException(413, "Структура превышает допустимый размер")
    result = normalize_seed(proposed)
    current = normalize_seed(current)
    if result.get("courseCode") != current.get("courseCode"):
        raise HTTPException(422, "Технический код курса нельзя менять")
    days = result.get("days")
    current_days = current.get("days")
    if (
        not isinstance(days, list)
        or not all(isinstance(day, dict) for day in days)
        or len(days) != 21
        or len(current_days) != 21
    ):
        raise HTTPException(422, "В Мастер-классе должно быть 21 день")
    if [day.get("number") for day in days] != list(range(1, 22)):
        raise HTTPException(422, "Порядок дней нельзя менять")

    for key in current:
        if key not in {"days"} and result.get(key) != current.get(key):
            raise HTTPException(422, f"Техническое поле курса нельзя менять: {key}")
    unexpected_course = set(result) - set(current)
    if unexpected_course:
        raise HTTPException(422, f"Неизвестное поле курса: {sorted(unexpected_course)[0]}")

    global_step_ids: set[str] = set()
    for day, old_day in zip(days, current_days, strict=True):
        day_number = int(day["number"])
        unexpected_day = set(day) - set(old_day) - DAY_EDITABLE
        if unexpected_day:
            raise HTTPException(
                422, f"День {day_number}: неизвестное поле {sorted(unexpected_day)[0]}"
            )
        for key in old_day:
            if key not in DAY_EDITABLE | {"steps", "checks"} and day.get(key) != old_day.get(key):
                raise HTTPException(422, f"День {day_number}: поле {key} нельзя менять")
        for key in DAY_EDITABLE:
            if key in day:
                if isinstance(day[key], str) and len(day[key]) > 50_000:
                    raise HTTPException(422, f"День {day_number}: поле {key} слишком длинное")
                if key in HTML_FIELDS:
                    day[key] = sanitize_fragment(day[key])
                elif isinstance(day[key], str):
                    day[key] = day[key].strip()
        if day.get("media") not in {"none", "video", "image", None}:
            raise HTTPException(422, f"День {day_number}: неизвестный тип медиа")
        if day.get("video") is not None and (
            isinstance(day["video"], bool)
            or not isinstance(day["video"], (int, float))
            or not 0 <= day["video"] <= 1440
        ):
            raise HTTPException(422, f"День {day_number}: неверная длительность видео")
        validate_url(day.get("image"), image=True)
        validate_url(day.get("videoId"))

        old_steps = list(old_day.get("steps", []))
        raw_steps = day.get("steps")
        if not isinstance(raw_steps, list) or not all(
            isinstance(step, dict) for step in raw_steps
        ):
            raise HTTPException(422, f"День {day_number}: материалы должны быть списком")
        proposed_steps = list(raw_steps)
        old_by_id = {step["id"]: step for step in old_steps}
        for step in proposed_steps:
            if not step.get("id"):
                raise HTTPException(422, "Добавление материалов выполняется через чат")
            step_id = str(step["id"])
            if step_id in global_step_ids:
                raise HTTPException(422, f"Повторяется ID материала: {step_id}")
            global_step_ids.add(step_id)

        existing_ids = [step["id"] for step in proposed_steps if step["id"] in old_by_id]
        if existing_ids != [step["id"] for step in old_steps]:
            raise HTTPException(422, f"День {day_number}: порядок материалов нельзя менять")
        if len(proposed_steps) != len(old_steps):
            raise HTTPException(422, "Добавление и удаление материалов выполняется через чат")

        for step in proposed_steps:
            old = old_by_id.get(step["id"])
            if old is None:
                raise HTTPException(422, "Добавление материалов выполняется через чат")
            unexpected_step = set(step) - set(old) - STEP_EDITABLE - {
                "requiredForAllAfterRevision"
            }
            if unexpected_step:
                raise HTTPException(
                    422,
                    f"Материал {step['id']}: неизвестное поле {sorted(unexpected_step)[0]}",
                )
            for key in old:
                if key not in STEP_EDITABLE | {"requiredForAllAfterRevision"}:
                    if step.get(key) != old.get(key):
                        raise HTTPException(
                            422, f"Материал {step['id']}: поле {key} нельзя менять"
                        )
            if old.get("hidden", False) and not step.get("hidden", False):
                step["requiredForAllAfterRevision"] = next_version
            else:
                previous = old.get("requiredForAllAfterRevision")
                if previous is not None:
                    step["requiredForAllAfterRevision"] = previous
            for key in ("title", "label", "summary"):
                if key in step and isinstance(step[key], str):
                    if len(step[key]) > 5_000:
                        raise HTTPException(422, f"Материал {step['id']}: текст слишком длинный")
                    step[key] = step[key].strip()
            if not (step.get("title") or step.get("label")):
                raise HTTPException(422, f"Материал {step['id']}: укажите название")
            duration = step.get("durationMinutes")
            if duration is not None and (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not 0 <= duration <= 1440
            ):
                raise HTTPException(
                    422, f"Материал {step['id']}: неверная длительность"
                )
            asset = step.get("contentAsset")
            if asset and not SAFE_ASSET.fullmatch(str(asset)):
                raise HTTPException(422, f"Материал {step['id']}: недопустимое имя файла")
            if asset:
                asset_path = (
                    COURSE_CONTENT_ROOT / "imported-draft" / str(asset)
                    if asset == "extracted-2026-08-23.json"
                    else COURSE_CONTENT_ROOT / "source-current" / str(asset)
                )
                if not asset_path.is_file():
                    raise HTTPException(
                        422, f"Материал {step['id']}: файл {asset} не найден"
                    )
            validate_url(step.get("image"), image=True)
            validate_url(step.get("videoId"))
        day["steps"] = proposed_steps

        old_checks = {
            item["id"]: item
            for index, raw in enumerate(old_day.get("checks", []))
            for item in [raw if isinstance(raw, dict) else {
                "id": check_id(day_number, index), "text": str(raw),
                "required": True, "hidden": False,
            }]
        }
        checks = day.get("checks")
        if (
            not isinstance(checks, list)
            or not checks
            or len(checks) > 200
            or not all(isinstance(item, dict) for item in checks)
        ):
            raise HTTPException(422, f"День {day_number}: добавьте хотя бы один пункт задания")
        seen_checks: set[str] = set()
        for item in checks:
            if not item.get("id"):
                item["id"] = f"day-{day_number}-check-{uuid.uuid4().hex[:12]}"
            item_id = str(item["id"])
            if item_id in seen_checks:
                raise HTTPException(422, f"День {day_number}: повторяется ID пункта")
            seen_checks.add(item_id)
            old = old_checks.get(item_id)
            unexpected_check = set(item) - {
                "id", "text", "required", "hidden", "requiredForAllAfterRevision"
            }
            if unexpected_check:
                raise HTTPException(
                    422, f"День {day_number}: неизвестное поле пункта задания"
                )
            item["text"] = str(item.get("text") or "").strip()
            if not item["text"] or len(item["text"]) > 5_000:
                raise HTTPException(422, f"День {day_number}: пустой пункт задания")
            item["required"] = old.get("required", True) if old else True
            item["hidden"] = bool(item.get("hidden", False))
            if old and old.get("hidden", False) and not item["hidden"]:
                item["requiredForAllAfterRevision"] = next_version
            elif old and old.get("requiredForAllAfterRevision") is not None:
                item["requiredForAllAfterRevision"] = old["requiredForAllAfterRevision"]
        missing = set(old_checks) - seen_checks
        if missing:
            raise HTTPException(422, "Пункты задания нельзя удалять — используйте «Скрыть»")
        day["checks"] = checks
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


def merge_seed_additions(current: dict, seed: dict, next_version: int) -> dict:
    """Add chat-managed seed steps without overwriting editor-owned course copy."""
    result = normalize_seed(current)
    seed_days = {int(day["number"]): day for day in normalize_seed(seed)["days"]}
    for day in result["days"]:
        seed_day = seed_days[int(day["number"])]
        merged_steps = list(day.get("steps", []))
        seed_steps = list(seed_day.get("steps", []))
        for seed_index, seed_step in enumerate(seed_steps):
            existing_ids = [step["id"] for step in merged_steps]
            if seed_step["id"] in existing_ids:
                continue
            added = deepcopy(seed_step)
            added["requiredForAllAfterRevision"] = next_version
            following = next(
                (
                    item["id"] for item in seed_steps[seed_index + 1:]
                    if item["id"] in existing_ids
                ),
                None,
            )
            if following is not None:
                merged_steps.insert(existing_ids.index(following), added)
                continue
            preceding = next(
                (
                    item["id"] for item in reversed(seed_steps[:seed_index])
                    if item["id"] in existing_ids
                ),
                None,
            )
            insert_at = existing_ids.index(preceding) + 1 if preceding else len(merged_steps)
            merged_steps.insert(insert_at, added)
        day["steps"] = merged_steps
    return result


def publish_course_seed_additions(db: Session, *, admin: str) -> ManagedDocumentVersion:
    current = active_course_version(db)
    payload = merge_seed_additions(
        current.payload,
        seed_manifest(),
        current.version_no + 1,
    )
    return publish_document(
        db,
        document_type=DOCUMENT_TYPE,
        document_key=DOCUMENT_KEY,
        schema_version=MANAGED_SCHEMA_VERSION,
        payload=payload,
        expected_version=current.version_no,
        admin=admin,
    )


def prepare_restore_payload(source: dict, current: dict, next_version: int) -> dict:
    restored = deepcopy(source)
    restored_days = {int(day["number"]): day for day in restored["days"]}
    for current_day in current["days"]:
        day = restored_days[int(current_day["number"])]
        merged_steps = []
        source_steps = {step["id"]: step for step in day.get("steps", [])}
        for current_step in current_day.get("steps", []):
            if current_step["id"] in source_steps:
                merged_steps.append(source_steps[current_step["id"]])
            else:
                hidden = deepcopy(current_step)
                hidden["hidden"] = True
                merged_steps.append(hidden)
        day["steps"] = merged_steps

        source_checks = {
            item["id"]: item for item in day.get("checks", []) if isinstance(item, dict)
        }
        merged_checks = list(day.get("checks", []))
        for item in current_day.get("checks", []):
            if item["id"] not in source_checks:
                hidden = deepcopy(item)
                hidden["hidden"] = True
                merged_checks.append(hidden)
        day["checks"] = merged_checks
    return normalize_editor_payload(restored, current, next_version)


def effective_required_step_ids(
    context: CourseContext, progress: MasterclassDayProgress, day_number: int
) -> list[str]:
    result: list[str] = []
    baseline = set(progress.required_step_ids or [])
    for step in context.days[day_number].get("steps", []):
        if step.get("hidden", False) or not step.get("required", True):
            continue
        reactivated = int(step.get("requiredForAllAfterRevision") or 0)
        if step["id"] in baseline or reactivated > progress.structure_revision_no:
            result.append(step["id"])
    return result


def effective_required_check_ids(
    context: CourseContext, progress: MasterclassDayProgress, day_number: int
) -> list[str]:
    result: list[str] = []
    baseline = set(progress.required_check_ids or [])
    for item in context.checks[day_number]:
        if item.get("hidden", False) or not item.get("required", True):
            continue
        reactivated = int(item.get("requiredForAllAfterRevision") or 0)
        if item["id"] in baseline or reactivated > progress.structure_revision_no:
            result.append(item["id"])
    return result
