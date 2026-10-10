"""Система рецептов: оглавление поверх опубликованных материалов Мастер-класса."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.course_material_service import material_source, published_materials
from app.course_structure_service import course_context
from app.masterclass_editorial import EDITABLE_MATERIALS
from app.models import ContentItem

COURSE_CODE = "recipes"
RESOURCE_CODE = "ACCESS_RECIPES"
# Порядок одновременно задаёт стабильные позиции отметок чтения. Не переставлять
# существующие позиции без переноса progress; текст и названия принадлежат МК.
GROUPS = (
    ("Организация питания", (
        "day-06-article-01", "day-06-article-02", "day-06-rule-1-percent",
    )),
    ("Вкус и приготовление", (
        "day-06-article-03", "day-07-video-01", "day-15-article-02", "day-07-store-food",
    )),
    ("Рецепты", ("day-15-recipes-part-2",)),
)
PLACEHOLDERS = {"day-07-store-food"}


def course_manifest(db: Session) -> dict:
    context = course_context(db)
    source_steps = {
        step["id"]: step
        for day in context.days.values() for step in day.get("steps", [])
    }
    published = set(EDITABLE_MATERIALS)
    source = material_source(db)
    if source:
        published.update(db.scalars(select(ContentItem.external_id).where(
            ContentItem.source_id == source.id,
            ContentItem.latest_version_id.is_not(None),
        )))
    groups = []
    # Порядок экрана меняется без переноса сохранённых отметок чтения.
    for number, group_index in enumerate((2, 0, 1), 1):
        title, ids = GROUPS[group_index]
        if group_index == 2:
            title = "Все рецепты"
            ids = (*ids, *(step["id"] for step in source_steps.values()
                          if step.get("nested")
                          and step.get("parentStepId") == "day-15-recipes-part-2"))
        steps = []
        for step_id in ids:
            original = source_steps.get(step_id, {})
            locked = (
                step_id in PLACEHOLDERS or step_id not in published
                or not original or original.get("hidden") or original.get("locked")
                or original.get("placeholder") or original.get("kind") != "article"
            )
            if original.get("nested"):
                parent = source_steps.get(original.get("parentStepId"), {})
                locked = locked or bool(not parent or parent.get("hidden")
                                        or parent.get("locked") or parent.get("placeholder")
                                        or parent.get("id") not in published)
            step = {key: original[key] for key in (
                "title", "summary", "durationMinutes", "image", "videoId", "imagePresentation",
                "nested", "parentStepId",
            ) if key in original}
            step.update(id=step_id, kind="article", required=not locked and not step.get("nested"),
                        locked=bool(locked), badge="Скоро" if locked else "")
            if not step.get("title"):
                step["title"] = original.get("label") or "Материал готовится"
            if step_id == "day-15-recipes-part-2":
                step["title"] = "Все рецепты"
            steps.append(step)
        groups.append({"number": number, "progressNumber": group_index + 1,
                       "title": title, "steps": steps, "checks": []})
    return {
        "courseVersion": f"recipes-2-mc-{context.revision.version_no}",
        "structureVersion": context.revision.version_no,
        "minimum_required_structure_revision": context.manifest.get("minimum_required_structure_revision", 0),
        "title": "Система рецептов", "navigation": "materials", "linearNavigation": True,
        "sourceCourse": "masterclass-21", "days": groups,
    }


def material_position(manifest: dict, step_id: str):
    return next((
        (group["number"], index, step)
        for group in manifest["days"] for index, step in enumerate(group["steps"])
        if step["id"] == step_id
    ), None)


def course_material(db: Session, manifest: dict, step_id: str) -> dict:
    found = material_position(manifest, step_id)
    if not found or found[2]["locked"]:
        return {"ok": True, "materials": {}}
    context = course_context(db)
    return published_materials(db, allowed_days=set(context.days), step_id=step_id,
                               allowed_step_ids={step_id})
