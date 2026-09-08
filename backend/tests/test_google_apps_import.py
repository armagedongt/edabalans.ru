from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.importers.google_apps import json_value, merge_dqs_days


def test_json_value_reads_google_sheet_day_payload() -> None:
    payload = '{"v":2,"updated":"2026-08-22T10:00:00Z","p":[1],"d":[true]}'

    assert json_value(payload) == {
        "v": 2,
        "updated": "2026-08-22T10:00:00Z",
        "p": [1],
        "d": [True],
    }
    assert json_value("") is None
    assert json_value("not json") is None


def test_dqs_merge_adds_missing_sheet_days_and_preserves_newer_native_days() -> None:
    existing = {
        "1": {"updated": "2026-09-01T10:00:00Z", "p": [2]},
        "3": {"updated": "2026-08-25T10:00:00Z", "p": [3]},
    }
    incoming = {
        "1": {"updated": "2026-08-22T10:00:00Z", "p": [1]},
        "2": {"updated": "2026-08-22T11:00:00Z", "p": [2]},
        "3": {"updated": "2026-08-26T10:00:00Z", "p": [4]},
    }

    merged, changed = merge_dqs_days(existing, incoming)

    assert changed == 2
    assert merged["1"]["p"] == [2]
    assert merged["2"]["p"] == [2]
    assert merged["3"]["p"] == [4]
