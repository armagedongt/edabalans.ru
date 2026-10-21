"""Template metadata uses the existing versioned StrengthState JSON document."""
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
