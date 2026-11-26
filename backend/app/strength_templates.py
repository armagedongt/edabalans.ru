"""Template metadata and membership use the versioned StrengthState document."""
from typing import Any


def normalize_templates(incoming: Any, previous: list[dict], workouts: list[dict]) -> list[dict]:
    if not isinstance(incoming, list) or not incoming or len(incoming) > 100:
        raise ValueError("INVALID_WORKOUT_TEMPLATES")
    previous_by_id = {int(item["workout_type"]): item for item in previous}
    historical_ids = {int(item.get("workout_type") or 0) for item in workouts}
    seen: set[int] = set()
    result = []
    for index, item in enumerate(incoming, 1):
        if not isinstance(item, dict):
            raise ValueError("INVALID_WORKOUT_TEMPLATE")
        raw_id = item.get("workout_type")
        if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id < 1 or raw_id > 1_000_000 or raw_id in seen:
            raise ValueError("INVALID_WORKOUT_TEMPLATE")
        title = str(item.get("title") or "").strip()
        if len(title) > 120:
            raise ValueError("INVALID_WORKOUT_TEMPLATE_TITLE")
        old = previous_by_id.get(raw_id)
        active = item.get("active") is not False
        if active and old and old.get("active") is False:
            raise ValueError("DELETED_WORKOUT_TEMPLATE")
        if active and old is None and raw_id in historical_ids:
            raise ValueError("WORKOUT_TEMPLATE_ID_IN_USE")
        seen.add(raw_id)
        result.append({"workout_type": raw_id, "title": title or f"Шаблон {raw_id}", "active": active, "sort_order": index})
    # Retain tombstones so deleted IDs cannot be silently reused by a later template.
    for template_id, item in previous_by_id.items():
        if template_id not in seen:
            result.append({**item, "active": False, "sort_order": len(result) + 1})
    return result


def template_exercise_settings(incoming: Any, templates: list[dict], catalog: list[dict], previous: list[dict]) -> list[dict]:
    """Replace the complete active board atomically, retaining catalog and history."""
    active_ids = {item["workout_type"] for item in templates if item.get("active") is not False}
    if not isinstance(incoming, list) or len(incoming) != len(active_ids):
        raise ValueError("INVALID_TEMPLATE_EXERCISES")
    known = {str(item["exercise_id"]): item for item in catalog}
    lists = {}
    for item in incoming:
        if not isinstance(item, dict):
            raise ValueError("INVALID_TEMPLATE_EXERCISES")
        template_id, ids = item.get("workout_type"), item.get("exercise_ids")
        if (type(template_id) is not int or template_id not in active_ids or template_id in lists
                or not isinstance(ids, list) or len(ids) > 250):
            raise ValueError("INVALID_TEMPLATE_EXERCISES")
        seen = set()
        for exercise_id in ids:
            if (not isinstance(exercise_id, str) or exercise_id not in known or exercise_id in seen
                    or known[exercise_id].get("catalog_active") is False):
                raise ValueError("INVALID_TEMPLATE_EXERCISE")
            seen.add(exercise_id)
        lists[template_id] = ids
    preserved = [item for item in previous if isinstance(item, dict) and
                 (item.get("scope") == "catalog" or int(item.get("workout_type") or 0) not in active_ids)]
    previous_by_key = {(int(item.get("workout_type") or 0), str(item.get("exercise_id") or "")): item
                       for item in previous if isinstance(item, dict) and item.get("scope") != "catalog"}
    for template_id, ids in lists.items():
        order = {exercise_id: index for index, exercise_id in enumerate(ids, 1)}
        for index, exercise_id in enumerate(known, len(ids) + 1):
            preserved.append({**previous_by_key.get((template_id, exercise_id), {}),
                              "workout_type": template_id, "exercise_id": exercise_id,
                              "active": exercise_id in order, "sort_order": order.get(exercise_id, index)})
    return preserved
