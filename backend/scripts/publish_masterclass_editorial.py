"""Publish the owner-edited Masterclass Markdown canon to the live runtime.

The structure update is versioned. Existing unlisted steps are retained and
hidden, so no source material is deleted. Positional progress follows stable IDs
when the editorial program changes the visible order.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import re

from sqlalchemy import select, text as sql_text

from app.article_markup import article_plain_text
from app.course_material_service import get_material, publish_material, render_material
from app.course_structure_service import (
    DOCUMENT_KEY,
    DOCUMENT_TYPE,
    MANAGED_SCHEMA_VERSION,
    active_course_version,
)
from app.database import SessionLocal
from app.managed_documents import publish_document
from app.models import MasterclassStepProgress
from scripts.bootstrap_masterclass_editorial import EDITORIAL, parse_program


MEDIA_PREFIX = "/course-assets/masterclass/media/"


def new_article_step(item: dict, *, next_version: int) -> dict:
    return {
        "id": item["step_id"],
        "kind": "article",
        "title": item["title"],
        "summary": "",
        "status": "ready",
        "contentKind": "text",
        "contentAsset": "55-store-food-without-cooking.md",
        "durationMinutes": item["duration"],
        "hidden": False,
        "requiredForAllAfterRevision": next_version,
    }


def compile_manifest(current: dict, *, next_version: int) -> tuple[dict, list[str]]:
    days, materials = parse_program()
    result = deepcopy(current)
    current_steps = {
        step["id"]: step
        for day in result["days"]
        for step in day.get("steps", [])
    }
    originally_hidden = {
        step_id: bool(step.get("hidden", False))
        for step_id, step in current_steps.items()
    }
    changes: list[str] = []
    for editorial_day, day in zip(days, result["days"], strict=True):
        day["title"] = editorial_day["title"]
        day["tocSummary"] = ""
        wanted = [item["step_id"] for item in editorial_day["materials"]]
        wanted_set = set(wanted)
        for step in day.get("steps", []):
            step["hidden"] = step["id"] not in wanted_set
        for item in editorial_day["materials"]:
            step = current_steps.get(item["step_id"])
            if step is None:
                if item["step_id"] != "day-07-store-food":
                    raise ValueError(f"Нет runtime-шаблона материала {item['step_id']}")
                step = new_article_step(item, next_version=next_version)
                day["steps"].append(step)
                current_steps[step["id"]] = step
                changes.append(f"день {editorial_day['number']}: добавлен {step['id']}")
            was_hidden = originally_hidden.get(step["id"], False)
            step["hidden"] = False
            step["title"] = item["title"]
            if "label" in step or step.get("kind") != "article":
                step["label"] = item["title"]
            step["summary"] = ""
            step["durationMinutes"] = item["duration"]
            if was_hidden:
                step["requiredForAllAfterRevision"] = next_version
            if item["step_id"] == "day-17-article-04":
                step["locked"] = True
                step["badge"] = "Скоро"
        visible = [current_steps[step_id] for step_id in wanted]
        hidden = [
            step for step in day.get("steps", [])
            if step["id"] not in wanted_set
        ]
        day["steps"] = visible + hidden
        changes.append(
            f"день {editorial_day['number']}: {editorial_day['title']} — "
            f"{len(wanted)} видимых материалов"
        )
    return result, changes


def editorial_body(path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r", "")
    text = re.sub(r"\A\ufeff?# [^\n]+\n+", "", text, count=1)
    text = re.sub(r"\A> Тип:.*?\n+", "", text, count=1)
    return re.sub(
        r"(!\[[^]]*]\()assets/",
        rf"\1{MEDIA_PREFIX}",
        text,
    ).strip() + "\n"


def special_prelude(path, material_type: str) -> str:
    body = editorial_body(path)
    if material_type == "questionnaire":
        body = body.split("## Вопросы", 1)[0].strip() + "\n"
    body = body.split("<!-- EMBED:", 1)[0].strip() + "\n"
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()
    return render_material(body, "markdown") if body.strip() else ""


def day_sections(path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8").replace("\r", "")
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    return {
        parts[index].strip(): parts[index + 1].strip()
        for index in range(1, len(parts), 2)
    }


def render_day_section(value: str) -> str:
    markdown = re.sub(
        r"<strong>(.*?)</strong>", r"**\1**", value, flags=re.IGNORECASE | re.DOTALL
    )
    return render_material(markdown, "markdown")


def apply_day_copy(manifest: dict, days: list[dict]) -> None:
    day_files = {
        int(match.group(1)): path
        for path in (EDITORIAL / "days").glob("*.md")
        for match in [re.match(r"(\d+)-", path.name)]
        if match
    }
    for editorial_day, day in zip(days, manifest["days"], strict=True):
        sections = day_sections(day_files[editorial_day["number"]])
        lead = sections.get("Перед вводным медиа", "")
        day["lead"] = article_plain_text(render_day_section(lead)) if lead else ""
        intro = sections.get("После вводного медиа", "")
        day["intro"] = render_day_section(intro) if intro else ""
        before = sections.get("Перед заданием", "")
        day["afterLead"] = ""
        day["afterTitle"] = ""
        day["afterText"] = render_day_section(before) if before else ""
        old_checks = list(day.get("checks", []))
        old_by_text = {
            str(item.get("text") or "").strip(): item
            for item in old_checks
            if isinstance(item, dict)
        }
        checks = []
        for index, line in enumerate(sections.get("Задание на сегодня", "").splitlines()):
            match = re.match(r"- \[[ xX]] (.+)", line.strip())
            if match:
                check_text = match.group(1).strip()
                old = old_by_text.get(check_text)
                digest = hashlib.sha256(check_text.encode("utf-8")).hexdigest()[:12]
                checks.append({
                    "id": (
                        old.get("id") if isinstance(old, dict) and old.get("id")
                        else f"day-{editorial_day['number']}-editorial-check-{digest}"
                    ),
                    "text": check_text,
                    "required": True,
                    "hidden": False,
                })
        if checks:
            used_ids = {item["id"] for item in checks}
            for old in old_checks:
                if isinstance(old, dict) and old.get("id") in used_ids:
                    continue
                hidden = deepcopy(old) if isinstance(old, dict) else {
                    "id": f"day-{editorial_day['number']}-legacy-check-{len(checks) + 1}",
                    "text": str(old),
                    "required": True,
                }
                hidden["hidden"] = True
                checks.append(hidden)
            day["checks"] = checks


def migrate_step_progress(db, before: dict, after: dict) -> int:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(sql_text(
            "LOCK TABLE masterclass_step_progress IN SHARE ROW EXCLUSIVE MODE"
        ))
    mappings: dict[int, dict[int, int]] = {}
    for old_day, new_day in zip(before["days"], after["days"], strict=True):
        new_indices = {step["id"]: index for index, step in enumerate(new_day["steps"])}
        mapping = {
            old_index: new_indices[step["id"]]
            for old_index, step in enumerate(old_day.get("steps", []))
        }
        if any(old != new for old, new in mapping.items()):
            mappings[int(old_day["number"])] = mapping
    rows = list(db.scalars(select(MasterclassStepProgress)))
    changed = []
    for row in rows:
        mapping = mappings.get(row.day_number)
        if mapping is not None and row.step_index in mapping:
            target = mapping[row.step_index]
            if target != row.step_index:
                changed.append((row, target))
                row.step_index += 10_000
    db.flush()
    for row, target in changed:
        row.step_index = target
    db.flush()
    return len(changed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    days, materials = parse_program()
    with SessionLocal() as db:
        current = active_course_version(db)
        manifest, changes = compile_manifest(
            current.payload, next_version=current.version_no + 1
        )
        apply_day_copy(manifest, days)
        rendered_articles = {
            item["step_id"]: editorial_body(item["path"])
            for item in materials.values()
            if item["type"] == "article" and item["step_id"] != "day-17-article-04"
        }
        for content in rendered_articles.values():
            render_material(content, "markdown")
        for item in materials.values():
            if item["type"] == "article":
                continue
            step = next(
                step
                for day in manifest["days"]
                for step in day["steps"]
                if step["id"] == item["step_id"]
            )
            step["editorialHtml"] = special_prelude(item["path"], item["type"])
        print(f"Текущая редакция структуры: {current.version_no}")
        print("\n".join(changes))
        if not args.publish:
            print("Проверка завершена; публикация не выполнялась")
            return
        published = publish_document(
            db,
            document_type=DOCUMENT_TYPE,
            document_key=DOCUMENT_KEY,
            schema_version=MANAGED_SCHEMA_VERSION,
            payload=manifest,
            expected_version=current.version_no,
            admin="markdown-canon-publisher",
            commit=False,
        )
        migrated_progress = migrate_step_progress(db, current.payload, manifest)
        published_articles = 0
        for item in materials.values():
            if item["type"] != "article" or item["step_id"] == "day-17-article-04":
                continue
            active = get_material(db, item["step_id"])
            publish_material(
                db,
                step_id=item["step_id"],
                content=rendered_articles[item["step_id"]],
                content_format="markdown",
                expected_version=active["version"],
                admin="markdown-canon-publisher",
                commit=False,
            )
            published_articles += 1
        db.commit()
        print(
            f"Опубликована структура {published.version_no}; "
            f"обновлено статей: {published_articles}; "
            f"перенесено отметок прогресса: {migrated_progress}"
        )


if __name__ == "__main__":
    main()
