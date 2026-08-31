from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path


os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.course_structure_service import prepare_20_day_migration


ROOT = Path(__file__).resolve().parents[2]
DESIRED = ROOT / "content" / "masterclass" / "course" / "course.json"


def test_migration_removes_legacy_day_without_touching_first_five_days():
    desired = json.loads(DESIRED.read_text(encoding="utf-8"))
    current = deepcopy(desired)
    current["days"][5]["title"] = "Legacy day 6"
    current["days"].append(
        {
            "number": 21,
            "slug": "day-21-legacy",
            "title": "Legacy final day",
            "tocSummary": "Legacy",
            "lead": "Legacy",
            "media": "none",
            "video": 0,
            "videoId": None,
            "image": None,
            "intro": "Legacy",
            "afterTitle": "",
            "afterText": "",
            "checks": [],
            "recipeDay": False,
            "publicationStatus": "ready",
            "steps": [],
            "implementation": {"notes": []},
            "afterLead": "",
            "timings": [],
        }
    )

    result, changes = prepare_20_day_migration(current, desired, next_version=99)

    assert [day["number"] for day in result["days"]] == list(range(1, 21))
    assert result["days"][:5] == current["days"][:5]
    assert any(change.startswith("day 6:") for change in changes)
    final_step_ids = {step["id"] for step in result["days"][-1]["steps"]}
    assert "day-21-article-01" in final_step_ids
    assert "day-21-offer" in final_step_ids


def test_migration_marks_reactivated_steps_for_new_participants():
    desired = json.loads(DESIRED.read_text(encoding="utf-8"))
    current = deepcopy(desired)
    current["days"][5]["steps"][0]["hidden"] = True

    result, _ = prepare_20_day_migration(current, desired, next_version=41)

    reactivated = result["days"][5]["steps"][0]
    assert reactivated["hidden"] is False
    assert reactivated["requiredForAllAfterRevision"] == 41
