"""Explicit conversion of the two legacy exercise catalogues, without changing results."""

from copy import deepcopy
from typing import Any


LEGACY_EXERCISE_IDS = {
    "extensions": "hyperextension",
    "squat": "back-squat",
    "row": "seated-row",
    "rdl": "romanian-deadlift",
    "hip_bridge": "hip-thrust",
    "incline_press": "incline-dumbbell-press",
    "pullup": "assisted-pull-up",
    "triceps": "triceps-pushdown",
    "lateral_raise": "lateral-raise",
    "biceps": "standing-curl",
    "abductor": "hip-abduction",
    "close_grip_bench_press": "close-grip-bench-press",
    "legacy-t1-верх-блок-на-трицепс": "triceps-pushdown",
    "legacy-t1-жим-на-наклонной": "incline-dumbbell-press",
    "legacy-t1-жим-штанги": "bench-press",
    "legacy-t2-сгибание-ног": "leg-curl",
    "legacy-t2-румынка": "romanian-deadlift",
    "legacy-t2-жим-в-гравитроне-без-отдыха": "gravitron-single-leg-press",
    "legacy-t1-грёбаная-тяга-в-тренажере": "seated-row",
    "legacy-t1-подтягивания": "assisted-pull-up",
    "legacy-t1-разведение-лежа": "dumbbell-fly",
    "legacy-t2-приседания": "back-squat",
    "legacy-t2-разведение-ног-с-наклоном-вперед": "hip-abduction",
    "legacy-t2-плечи-тренажер": "machine-lateral-raise",
    "legacy-t1-подтягивания-в-гравитроне": "assisted-pull-up",
    "legacy-t1-плечи-тренажер": "machine-lateral-raise",
}


def normalize_exercise_catalog(
    workouts: list[dict[str, Any]],
    settings: list[dict[str, Any]],
    names: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return copied history/settings; refuse ambiguous or colliding conversions.

    The explicit note on the first assisted session determines the split of the
    old mixed pulldown/pullup row. Template membership follows its latest meaning.
    The caller must restrict this operation to the approved legacy profiles.
    """
    after_workouts = deepcopy(workouts)
    after_settings = deepcopy(settings)
    mixed = [
        (workout, exercise)
        for workout in after_workouts
        for exercise in workout.get("exercises", [])
        if exercise.get("exercise_id") == "pullup"
    ]
    boundary: int | None = None
    if mixed:
        markers = [
            int(workout["session_number"])
            for workout, exercise in mixed
            if "подтягивания в гравитроне" in str(exercise.get("note") or "").lower()
        ]
        if not markers:
            raise ValueError("Mixed pullup history requires an explicit assisted-pullup note")
        boundary = min(markers)

    def convert(item: dict[str, Any], number: int | None = None) -> None:
        old_id = str(item.get("exercise_id") or "")
        new_id = LEGACY_EXERCISE_IDS.get(old_id, old_id)
        if old_id == "pullup" and number is not None and boundary is not None and number < boundary:
            new_id = "lat-pulldown"
        if new_id not in names:
            return
        if old_id != new_id:
            item.setdefault("legacy_exercise_id", old_id)
        if "exercise_name" in item:
            if item["exercise_name"] != names[new_id]:
                item.setdefault("legacy_exercise_name", item["exercise_name"])
            item["exercise_name"] = names[new_id]
        item["exercise_id"] = new_id

    for workout in after_workouts:
        ids: set[str] = set()
        for exercise in workout.get("exercises", []):
            convert(exercise, int(workout["session_number"]))
            exercise_id = exercise["exercise_id"]
            if exercise_id in ids:
                raise ValueError("Exercise conversion would combine results in one session")
            ids.add(exercise_id)

    # A legacy active alias and its inactive base entry can coexist in a template.
    # Preserve the active entry's position rather than hiding the exercise.
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for setting in after_settings:
        convert(setting)
        if setting.get("scope") == "catalog" and setting.get("exercise_id") in names:
            continue  # Base metadata now owns this known exercise.
        key = (setting.get("scope"), setting.get("workout_type"), setting.get("exercise_id"))
        previous = unique.get(key)
        if previous is None or (setting.get("active") is True and previous.get("active") is not True):
            unique[key] = setting
        elif setting.get("active") is True and previous.get("active") is True:
            previous["sort_order"] = min(int(previous.get("sort_order") or 0), int(setting.get("sort_order") or 0))
    return after_workouts, list(unique.values())
