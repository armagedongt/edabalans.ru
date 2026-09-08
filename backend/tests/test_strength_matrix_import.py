from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.importers.strength_matrix import matrix_payload


def sheet() -> list[list[object]]:
    rows: list[list[object]] = [[""] * 18 for _ in range(15)]
    rows[0][0] = "Упражнение"
    rows[1][2] = "План"
    rows[1][8] = "План"  # Irregular spacer before the second session.
    for column in (2, 8):
        rows[2][column : column + 5] = ["Вес", "Повторения", "Вес", "Повторения", "RPE"]
    rows[3][0] = "Разгибания"
    rows[4][0] = "#1"
    rows[5][0] = "#2"
    rows[7][0] = "Вторая тренировка"
    rows[8][0] = "Жим гантелей на наклонной скамье"
    rows[9][0] = "#1"
    rows[10][0] = "#2"
    rows[4][2:7] = ["10", "12", "11,5", "10", "8"]
    rows[5][2:7] = ["макс", "", "", "", ""]
    rows[9][2:7] = ["5", "15", "6", "14", "7"]
    rows[3][8] = "Локти мягкие"
    rows[4][8:13] = ["12", "10", "12", "9", "9"]
    rows[10][8:13] = ["", "", "7", "12", ""]
    return rows


def test_matrix_import_finds_vertical_exercises_and_irregular_training_columns() -> None:
    payload = matrix_payload(sheet())

    sessions = payload["strength_sessions"][1:]
    assert [(row[2], row[3], row[5]) for row in sessions] == [
        (1, 1, "filled"),
        (2, 1, "filled"),
        (1, 2, "filled"),
        (2, 2, "planned"),
    ]
    assert [row[2] for row in payload["strength_catalog"][1:]] == [
        "extensions",
        "incline_press",
    ]


def test_matrix_import_preserves_raw_text_and_parses_only_safe_numbers() -> None:
    payload = matrix_payload(sheet())
    headers = payload["strength_sets"][0]
    records = [dict(zip(headers, row, strict=True)) for row in payload["strength_sets"][1:]]

    first = next(row for row in records if row["session_id"].endswith("t1_s01") and row["set_number"] == 1)
    assert first["fact_weight"] == 11.5
    assert first["fact_weight_raw"] == "11,5"

    textual = next(row for row in records if row["session_id"].endswith("t1_s01") and row["set_number"] == 2)
    assert textual["plan_weight"] == ""
    assert textual["plan_weight_raw"] == "макс"


def test_matrix_import_keeps_heading_notes_and_unlabelled_sets() -> None:
    values = sheet()
    values[11][8:13] = ["", "", "8", "11", "8"]
    payload = matrix_payload(values)
    headers = payload["strength_session_exercises"][0]
    exercises = [dict(zip(headers, row, strict=True)) for row in payload["strength_session_exercises"][1:]]
    second = next(row for row in exercises if row["session_id"].endswith("t1_s02"))
    assert second["note"] == "Локти мягкие"
