from __future__ import annotations

import importlib.util
from copy import deepcopy
import json
import os
from pathlib import Path
from unittest.mock import MagicMock


os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "work" / "content-authoring-system" / "publish_final_masterclass_structure.py"
DESIRED = ROOT / "content" / "masterclass" / "course" / "course.json"


def load_module():
    spec = importlib.util.spec_from_file_location("publish_final_masterclass", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_merge_approved_migrates_legacy_structure_without_touching_first_five_days():
    module = load_module()
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

    result, changes = module.merge_approved(current, desired, next_version=99)

    assert [day["number"] for day in result["days"]] == list(range(1, 21))
    assert result["days"][:5] == current["days"][:5]
    assert any(change.startswith("day 6:") for change in changes)
    final_step_ids = {step["id"] for step in result["days"][-1]["steps"]}
    assert "day-21-article-01" in final_step_ids
    assert "day-21-offer" in final_step_ids


def test_merge_approved_marks_reactivated_steps_for_existing_participants():
    module = load_module()
    desired = json.loads(DESIRED.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(desired))
    current_step = current["days"][5]["steps"][0]
    current_step["hidden"] = True

    result, _ = module.merge_approved(current, desired, next_version=41)

    reactivated = result["days"][5]["steps"][0]
    assert reactivated["hidden"] is False
    assert reactivated["requiredForAllAfterRevision"] == 41


def test_prepare_masterclass_catalog_updates_active_managed_copy_without_resetting_it():
    module = load_module()
    current = {
        "schemaVersion": 2,
        "products": [
            {
                "code": "masterclass",
                "shortName": "Мастер-класс",
                "fullName": "Мастер-класс",
                "descriptor": "Как пройти программу",
                "status": "active",
                "marketing": "Авторская правка. 21-дневная программа Мастер-класса.",
            }
        ],
        "tariffs": [],
    }

    result, changed = module.prepare_masterclass_catalog(current)

    assert changed is True
    assert result["products"][0]["marketing"] == (
        "Авторская правка. 20-дневная программа Мастер-класса."
    )
    assert current["products"][0]["marketing"].endswith(
        "21-дневная программа Мастер-класса."
    )


def test_affected_progress_counts_covers_every_changed_day_from_six_onward():
    module = load_module()
    db = MagicMock()
    db.scalar.side_effect = [7, 11]

    assert module.affected_progress_counts(db) == (7, 11)
    statements = [call.args[0] for call in db.scalar.call_args_list]
    assert all("day_number >=" in str(statement) for statement in statements)
    assert all(6 in statement.compile().params.values() for statement in statements)


def test_release_remains_disabled_until_progress_strategy_is_approved():
    module = load_module()

    try:
        module.ensure_release_authorized()
    except SystemExit as exc:
        assert "migration strategy" in str(exc)
    else:
        raise AssertionError("release guard did not stop apply")
