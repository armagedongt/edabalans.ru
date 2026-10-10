"""Addressed course edits; existing documents, materials and participant progress."""
from __future__ import annotations

from copy import deepcopy
import difflib
import json
import re
from fastapi import HTTPException
from sqlalchemy import select, or_
from app import course_structure_service as masterclass
from app import calorie_course_service as calories
from app.course_structure_lock import lock_course
from app.managed_documents import publish_document
from app.models import (MasterclassStepProgress, MasterclassDayProgress, CourseStepProgress,
                        CourseStageProgress, CourseEvent)


def service(course_code):
    if course_code == "calories":
        return calories
    if course_code != "masterclass-21":
        raise HTTPException(404, "Курс не найден")
    return masterclass


def positions(manifest):
    found = {}
    for unit in manifest["days"]:
        for index, step in enumerate(unit["steps"]):
            if step["id"] in found:
                raise HTTPException(422, "Повтор ID в структуре")
            found[step["id"]] = (int(unit["number"]), index)
    return found


def grouped(steps):
    ids = {step["id"] for step in steps}
    for index, step in enumerate(steps):
        parent = step.get("parentStepId") if step.get("nested") else None
        if parent and (parent not in ids or parent not in {item["id"] for item in steps[:index]}):
            raise HTTPException(422, "Вложенный материал должен следовать за своим родителем")
    for parent in steps:
        children = [index for index, step in enumerate(steps) if step.get("parentStepId") == parent["id"]]
        if children:
            parent_index = steps.index(parent)
            if children != list(range(parent_index + 1, parent_index + 1 + len(children))):
                raise HTTPException(422, "Родитель и вложенные статьи перемещаются единым блоком")


def build(current, operation, next_version):
    proposed = deepcopy(current)
    units = {int(unit["number"]): unit for unit in proposed["days"]}
    old_positions = positions(current)
    kind = operation["type"]
    source_number = None
    moved = []
    target = units.get(operation["unit"])
    if target is None:
        raise HTTPException(422, "День или этап не существует")
    if kind == "reorder":
        old_ids = [step["id"] for step in target["steps"]]
        ids = operation["ids"]
        if len(ids) != len(set(ids)) or set(ids) != set(old_ids):
            raise HTTPException(422, "Нужна точная перестановка всех ID дня или этапа")
        by_id = {step["id"]: step for step in target["steps"]}
        target["steps"] = [by_id[ident] for ident in ids]
    elif kind == "add_article":
        ident = operation["id"]
        if ident in old_positions or not re.fullmatch(r"[a-z0-9-]{1,160}", ident):
            raise HTTPException(422, "Нужен новый устойчивый ID статьи")
        article = {"id": ident, "kind": "article", "contentKind": "text", "title": operation["title"],
                   "summary": operation.get("summary", ""), "required": operation["required"],
                   "hidden": False, "locked": False}
        article["title"] = article["title"].strip()
        if not article["title"]:
            raise HTTPException(422, "Название статьи не должно быть пустым")
        if operation["required"] and operation["required_for_existing"]:
            article["requiredForAllAfterRevision"] = next_version
        moved = [article]
    elif kind == "move":
        ident = operation["id"]
        if ident not in old_positions:
            raise HTTPException(422, "Материал не существует")
        source_number, _ = old_positions[ident]
        if source_number == operation["unit"]:
            raise HTTPException(422, "Внутри дня используйте reorder")
        source = units[source_number]
        root = next(step for step in source["steps"] if step["id"] == ident)
        if root.get("nested"):
            raise HTTPException(422, "Переносите родительский блок целиком")
        moved = [root, *(step for step in source["steps"] if step.get("parentStepId") == ident)]
        if any(step.get("kind") != "article" or step.get("contentKind") == "tutorial"
               or step.get("revealApp") for step in moved):
            raise HTTPException(422, "Специальный шаг требует своего runtime workflow")
        moved_ids = {step["id"] for step in moved}
        source["steps"] = [step for step in source["steps"] if step["id"] not in moved_ids]
        for step in moved:
            if step.get("required", True):
                step["requiredForAllAfterRevision"] = next_version if operation["required_for_existing"] else 0
    else:
        raise HTTPException(422, "Неизвестная структурная операция")
    if moved:
        anchor = operation.get("before_id")
        ids = [step["id"] for step in target["steps"]]
        if anchor is not None and anchor not in ids:
            raise HTTPException(422, "Материал-якорь не найден в целевом дне")
        index = ids.index(anchor) if anchor is not None else len(ids)
        target["steps"][index:index] = moved
    for number in {operation["unit"], source_number} - {None}:
        grouped(units[number]["steps"])
    if proposed != current:
        proposed["minimum_required_structure_revision"] = next_version
    if "stages" in proposed:
        proposed["stages"] = proposed["days"]
    return proposed, source_number, [step["id"] for step in moved]


def preview(db, course_code, expected_version, operation):
    native = service(course_code)
    lock_course(db, course_code)
    current = native.active_course_version(db)
    if current.version_no != expected_version:
        raise HTTPException(409, "Структура изменилась; получите актуальную версию")
    before = native.runtime_manifest(current.payload)
    after, source_unit, moved_ids = build(before, operation, current.version_no + 1)
    diff = "\n".join(difflib.unified_diff(json.dumps(before, ensure_ascii=False, indent=2).splitlines(),
        json.dumps(after, ensure_ascii=False, indent=2).splitlines(), fromfile="до", tofile="после", lineterm=""))
    return {"ok": True, "expected_version": current.version_no, "diff": diff, "manifest": after,
            "source_unit": source_unit, "moved_ids": moved_ids,
            "warnings": ["Завершённые дни/этапы не открываются заново; даты и события завершения сохраняются.",
                         "Порядок шагов меняет последовательность обязательных действий."]}


def recipe_positions(manifest):
    from app.recipe_course_service import GROUPS
    all_steps = [step for day in manifest["days"] for step in day["steps"]]
    result = {}
    for group_index, (_, fixed) in enumerate(GROUPS):
        ids = list(fixed)
        if group_index == 2:
            ids.extend(step["id"] for step in all_steps if step.get("nested")
                       and step.get("parentStepId") == "day-15-recipes-part-2")
        result.update({ident: (group_index + 1, index) for index, ident in enumerate(ids)})
    return result


def remap_rows(db, course_code, before, after, *, coordinate_maps=None):
    old, new = coordinate_maps or (positions(before), positions(after))
    affected = {position[0] for ident, position in old.items() if new.get(ident) != position}
    affected.update(new[ident][0] for ident, position in old.items() if new.get(ident) != position and ident in new)
    if not affected:
        return 0
    if course_code == "masterclass-21":
        rows = list(db.scalars(select(MasterclassStepProgress).where(
            MasterclassStepProgress.day_number.in_(affected)).with_for_update()))
        for row in rows:
            ident = row.step_id
            if ident is None:
                ident = next((key for key, pos in old.items() if pos == (row.day_number, row.step_index)), None)
            if ident not in old or old[ident] != (row.day_number, row.step_index):
                raise HTTPException(409, "Отметка Мастер-класса не совпадает с прежней структурой")
            row.day_number, row.step_index = new[ident]
        return len(rows)
    rows = list(db.scalars(select(CourseStepProgress).where(CourseStepProgress.course_code == course_code,
                CourseStepProgress.stage_number.in_(affected)).with_for_update()))
    reverse = {pos: ident for ident, pos in old.items()}
    targets = []
    for row in rows:
        ident = reverse.get((row.stage_number, row.step_index))
        if ident not in new:
            raise HTTPException(409, "Отметка курса не совпадает с прежней структурой")
        targets.append((row, new[ident]))
    offset = max([index for _, index in old.values()] + [index for _, index in new.values()]
                 + [row.step_index for row in rows] + [0]) + 1
    for number, (row, _) in enumerate(targets):
        row.step_index = offset + number
    db.flush()
    for row, (unit, index) in targets:
        row.stage_number, row.step_index = unit, index
    events = list(db.scalars(select(CourseEvent).where(CourseEvent.course_code == course_code,
                       CourseEvent.event_type == "calories_material_completed",
                       or_(*(CourseEvent.event_key.like(f"stage:{unit}:step:%") for unit in affected))).with_for_update()))
    event_targets = []
    for event in events:
        ident = (event.details or {}).get("step_id")
        if ident not in old or event.event_key != f"stage:{old[ident][0]}:step:{old[ident][1]}:completed":
            raise HTTPException(409, "Событие курса не совпадает с прежней структурой")
        event_targets.append((event, new[ident]))
        event.event_key = "structure-remap:" + str(event.id)
    db.flush()
    for event, (unit, index) in event_targets:
        event.event_key = f"stage:{unit}:step:{index}:completed"
        event.details = {**event.details, "stage": unit, "step_index": index}
    return len(rows)


def move_obligations(db, course_code, source, target, moved_ids):
    if source is None:
        return
    model = MasterclassDayProgress if course_code == "masterclass-21" else CourseStageProgress
    statement = select(model)
    if model is CourseStageProgress:
        statement = statement.where(model.course_code == course_code)
    unit_field = "day_number" if model is MasterclassDayProgress else "stage_number"
    rows = list(db.scalars(statement.where(getattr(model, unit_field).in_({source, target})).with_for_update()))
    targets = {row.user_id: row for row in rows if getattr(row, unit_field) == target}
    for row in rows:
        if getattr(row, unit_field) != source:
            continue
        owned = [ident for ident in row.required_step_ids if ident in moved_ids]
        row.required_step_ids = [ident for ident in row.required_step_ids if ident not in moved_ids]
        destination = targets.get(row.user_id)
        if destination is not None:
            destination.required_step_ids = list(dict.fromkeys([*destination.required_step_ids, *owned]))


def apply(db, course_code, expected_version, operation, admin):
    native = service(course_code)
    lock_course(db, course_code, exclusive=True)
    native.course_context(db)
    # A first seed may commit; reacquire before selecting the actual revision.
    lock_course(db, course_code, exclusive=True)
    current = native.active_course_version(db)
    if current.version_no != expected_version:
        raise HTTPException(409, "Структура изменилась; повторно сравните diff")
    before = native.runtime_manifest(current.payload)
    after, source, moved_ids = build(before, operation, expected_version + 1)
    if after == before:
        return {"ok": True, "version": expected_version, "changed": False, "remapped_rows": 0}
    try:
        count = remap_rows(db, course_code, before, after)
        if course_code == "masterclass-21":
            count += remap_rows(db, "recipes", before, after,
                                coordinate_maps=(recipe_positions(before), recipe_positions(after)))
        move_obligations(db, course_code, source, operation["unit"], moved_ids)
        revision = publish_document(db, document_type=native.DOCUMENT_TYPE, document_key=course_code,
            schema_version=native.MANAGED_SCHEMA_VERSION, payload=after, expected_version=expected_version,
            admin=admin, commit=False)
        from app import course_material_service as mk_material
        from app import calorie_course_material_service as calorie_material
        material = mk_material if course_code == "masterclass-21" else calorie_material
        if operation["type"] == "add_article":
            if material.material_item(db, operation["id"]) is not None:
                raise HTTPException(409, "ID статьи уже существует в каталоге материалов")
            from app.editorial_media import ingest
            import base64
            images = operation.get("media", [])
            try:
                size = sum(len(base64.b64decode(image["content_base64"], validate=True)) for image in images)
            except (ValueError, KeyError) as exc:
                raise HTTPException(422, "Некорректные байты фотографии") from exc
            if size > 4 * 1024 * 1024:
                raise HTTPException(413, "Новые фотографии статьи превышают 4 MiB")
            for image in images:
                ingest(db, scope=f"course:{course_code}:{operation['id']}", source=image, admin=admin, commit=False)
            material.publish_material(db, step_id=operation["id"], content=operation["content"],
                content_format="markdown", expected_version=0, admin=admin, commit=False)
        if operation["type"] == "move":
            for ident in moved_ids:
                item = material.material_item(db, ident, for_update=True)
                if item is not None:
                    unit = operation["unit"]
                    prefix = "day" if course_code == "masterclass-21" else "stage"
                    app = "masterclass" if course_code == "masterclass-21" else "calories"
                    query = "course" if course_code == "masterclass-21" else "calories"
                    item.canonical_url = f"https://edabalans.ru/apps/{app}-course.html?{query}_{prefix}={unit}&{query}_material={ident}"
                    item.source_tags = [tag for tag in item.source_tags if not re.fullmatch(prefix + r"-\d+", tag)] + [f"{prefix}-{unit}"]
        db.commit()
        return {"ok": True, "version": revision.version_no, "changed": True, "remapped_rows": count,
                "moved_ids": moved_ids}
    except Exception:
        db.rollback()
        raise
