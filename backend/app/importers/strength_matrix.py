from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.request
from collections import defaultdict
from typing import Any

from app.database import SessionLocal
from app.importers.google_apps import import_strength


SOURCE = "google_strength_original"
DEFAULT_USER_ID = "valentina_kapitanova"
DEFAULT_DISPLAY_NAME = "Валентина Капитанова"

EXERCISE_IDS = {
    "разгибания": "extensions",
    "приседания": "squat",
    "приседания со штангой": "squat",
    "тяга блока к поясу": "row",
    "тяга горизонтального блока": "row",
    "тяга верх блока (теперь подтягивания в гравитроне)": "pullup",
    "подтягивания": "pullup",
    "румынская тяга": "rdl",
    "ягодичный мост": "hip_bridge",
    "жим гантелей на наклонной скамье": "incline_press",
    "тяга верхнего блока (трицепс)": "triceps",
    "разгибания на трицепс": "triceps",
    "разведение ног в тренажере": "abductor",
    "отведение бедра в тренажере": "abductor",
    "разведение гантелей в сторону": "lateral_raise",
    "махи гантелей стоя": "lateral_raise",
    "подьем гантелей на бицепс": "biceps",
    "подъём гантелей на бицепс": "biceps",
}


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def row_value(rows: list[list[Any]], row: int, column: int) -> Any:
    if row < 0 or row >= len(rows) or column < 0 or column >= len(rows[row]):
        return ""
    return rows[row][column]


def numeric(value: Any) -> int | float | str:
    raw = text(value)
    if not raw:
        return ""
    normalized = raw.replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", normalized):
        return ""
    number = float(normalized)
    return int(number) if number.is_integer() else number


def exercise_sections(rows: list[list[Any]]) -> list[dict[str, Any]]:
    headings: list[tuple[int, str, int]] = []
    workout_type = 1
    for row_index, row in enumerate(rows):
        label = text(row[0] if row else "")
        normalized = label.casefold()
        if normalized.startswith("вторая трениров"):
            workout_type = 2
            continue
        if (
            row_index < 3
            or not label
            or label.startswith("#")
            or normalized in {"упражнение", "первая тренировка"}
        ):
            continue
        headings.append((row_index, label, workout_type))

    sections: list[dict[str, Any]] = []
    for index, (heading_row, name, kind) in enumerate(headings):
        end_row = headings[index + 1][0] if index + 1 < len(headings) else len(rows)
        if index + 1 < len(headings) and headings[index + 1][2] != kind:
            end_row = headings[index + 1][0]
        key = name.casefold().replace("ё", "е")
        exercise_id = EXERCISE_IDS.get(key)
        if not exercise_id:
            raise ValueError(f"Неизвестное упражнение в строке {heading_row + 1}: {name}")
        sections.append(
            {
                "exercise_id": exercise_id,
                "exercise_name": name,
                "workout_type": kind,
                "heading_row": heading_row,
                "start_row": heading_row + 1,
                "end_row": end_row,
            }
        )
    return sections


def group_starts(rows: list[list[Any]]) -> list[int]:
    header = rows[1] if len(rows) > 1 else []
    return [index for index, value in enumerate(header) if text(value).casefold() == "план"]


def set_payload(rows: list[list[Any]], row: int, column: int, set_number: int) -> dict[str, Any] | None:
    keys = ("plan_weight", "plan_reps", "fact_weight", "fact_reps", "rpe")
    values = [row_value(rows, row, column + offset) for offset in range(5)]
    if not any(text(value) for value in values):
        return None
    result: dict[str, Any] = {"set_number": set_number, "source": SOURCE}
    for key, value in zip(keys, values, strict=True):
        result[key] = numeric(value)
        result[f"{key}_raw"] = text(value)
    return result


def matrix_payload(
    rows: list[list[Any]],
    *,
    legacy_user_id: str = DEFAULT_USER_ID,
    display_name: str = DEFAULT_DISPLAY_NAME,
) -> dict[str, list[list[Any]]]:
    sections = exercise_sections(rows)
    starts = group_starts(rows)
    if not sections or not starts:
        raise ValueError("В таблице не найдены упражнения или колонки тренировок")

    users = [["user_id", "email", "display_name", "status"], [legacy_user_id, "", display_name, "active"]]
    types = [
        ["user_id", "workout_type", "title", "active", "sort_order"],
        [legacy_user_id, 1, "Тренировка 1", True, 1],
        [legacy_user_id, 2, "Тренировка 2", True, 2],
    ]
    catalog = [["user_id", "workout_type", "exercise_id", "exercise_name", "active", "sort_order"]]
    order_by_type: dict[int, int] = defaultdict(int)
    for section in sections:
        kind = section["workout_type"]
        order_by_type[kind] += 1
        section["sort_order"] = order_by_type[kind]
        catalog.append(
            [legacy_user_id, kind, section["exercise_id"], section["exercise_name"], True, section["sort_order"]]
        )

    sessions = [["session_id", "user_id", "workout_type", "session_number", "date", "status", "legacy_group", "source"]]
    session_exercises = [["session_id", "exercise_id", "exercise_name", "sort_order", "note", "source"]]
    sets = [[
        "session_id", "exercise_id", "set_number", "plan_weight", "plan_reps", "fact_weight", "fact_reps", "rpe",
        "plan_weight_raw", "plan_reps_raw", "fact_weight_raw", "fact_reps_raw", "rpe_raw", "source",
    ]]

    for session_number, column in enumerate(starts, 1):
        for workout_type in (1, 2):
            session_id = f"{legacy_user_id}_t{workout_type}_s{session_number:02d}"
            exercise_rows: list[list[Any]] = []
            set_rows: list[list[Any]] = []
            has_rpe = False
            for section in [item for item in sections if item["workout_type"] == workout_type]:
                note_values = [text(row_value(rows, section["heading_row"], column + offset)) for offset in range(5)]
                note = " · ".join(dict.fromkeys(value for value in note_values if value))
                own_sets: list[dict[str, Any]] = []
                fallback_number = 0
                for row_index in range(section["start_row"], section["end_row"]):
                    result = set_payload(rows, row_index, column, fallback_number + 1)
                    if result is None:
                        continue
                    fallback_number += 1
                    label = text(row_value(rows, row_index, 0)).lstrip("#")
                    number = int(label) if label.isdigit() else fallback_number
                    result["set_number"] = number
                    has_rpe = has_rpe or bool(result["rpe_raw"])
                    own_sets.append(result)
                if not note and not own_sets:
                    continue
                exercise_rows.append(
                    [session_id, section["exercise_id"], section["exercise_name"], section["sort_order"], note, SOURCE]
                )
                for item in own_sets:
                    set_rows.append(
                        [session_id, section["exercise_id"], item["set_number"]]
                        + [item[key] for key in ("plan_weight", "plan_reps", "fact_weight", "fact_reps", "rpe")]
                        + [item[key] for key in ("plan_weight_raw", "plan_reps_raw", "fact_weight_raw", "fact_reps_raw", "rpe_raw")]
                        + [SOURCE]
                    )
            if not exercise_rows:
                continue
            sessions.append(
                [session_id, legacy_user_id, workout_type, session_number, "", "filled" if has_rpe else "planned", f"column_{column + 1}", SOURCE]
            )
            session_exercises.extend(exercise_rows)
            sets.extend(set_rows)

    return {
        "strength_users": users,
        "strength_types": types,
        "strength_catalog": catalog,
        "strength_sessions": sessions,
        "strength_session_exercises": session_exercises,
        "strength_sets": sets,
    }


def run(rows: list[list[Any]], *, dry_run: bool, legacy_user_id: str, display_name: str) -> dict[str, int]:
    payload = matrix_payload(rows, legacy_user_id=legacy_user_id, display_name=display_name)
    summary: defaultdict[str, int] = defaultdict(int)
    with SessionLocal() as db:
        import_strength(db, payload, summary)
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return dict(summary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Записать импорт в базу; без флага выполняется dry-run")
    parser.add_argument("--backup-confirmed", action="store_true", help="Подтвердить свежий backup и test restore")
    parser.add_argument("--legacy-user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--display-name", default=DEFAULT_DISPLAY_NAME)
    parser.add_argument(
        "--csv-url",
        help="Публичный CSV-export исходного листа; без параметра матрица читается как JSON из stdin",
    )
    args = parser.parse_args()
    if args.apply and not args.backup_confirmed:
        parser.error("--apply requires --backup-confirmed")
    if args.csv_url:
        with urllib.request.urlopen(args.csv_url, timeout=30) as response:
            content = response.read().decode("utf-8-sig")
        values = list(csv.reader(io.StringIO(content)))
    else:
        values = json.load(sys.stdin)
    print(
        json.dumps(
            run(
                values,
                dry_run=not args.apply,
                legacy_user_id=args.legacy_user_id,
                display_name=args.display_name,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
