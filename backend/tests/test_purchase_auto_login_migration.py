import importlib.util
from pathlib import Path

import pytest


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "20260921_0047_purchase_auto_login_messenger_policy.py"
)
SPEC = importlib.util.spec_from_file_location("purchase_auto_login_migration", MIGRATION_PATH)
MIGRATION = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MIGRATION)


def _payload():
    return {
        "days": [
            {
                "number": 1,
                "steps": [
                    {"id": "day-01-article-01"},
                    {"id": "day-01-messenger-link", "hidden": True},
                    {"id": "day-01-article-02"},
                    {"id": "day-01-questionnaire"},
                ],
            }
        ]
    }


def test_progress_mapping_uses_old_active_order_before_policy_reorder():
    payload = _payload()
    rows = [
        {"id": "row-1", "user_id": "user-1", "day_number": 1, "step_index": 2},
        {"id": "row-2", "user_id": "user-1", "day_number": 1, "step_index": 3},
    ]

    assignments = MIGRATION._stable_step_assignments(payload, rows)
    published = MIGRATION._policy_v2_payload(payload)

    assert assignments == [
        ("row-1", "day-01-article-02"),
        ("row-2", "day-01-questionnaire"),
    ]
    assert [step["id"] for step in published["days"][0]["steps"]] == [
        "day-01-article-01",
        "day-01-article-02",
        "day-01-messenger-link",
        "day-01-questionnaire",
    ]
    assert published["days"][0]["steps"][2]["hidden"] is False
    assert payload["days"][0]["steps"][1]["hidden"] is True


def test_progress_mapping_rejects_unknown_position_and_duplicate_stable_completion():
    with pytest.raises(RuntimeError, match="Unmapped masterclass progress"):
        MIGRATION._stable_step_assignments(
            _payload(),
            [{"id": "bad", "user_id": "user-1", "day_number": 1, "step_index": 99}],
        )

    duplicate = [
        {"id": "row-1", "user_id": "user-1", "day_number": 1, "step_index": 0},
        {"id": "row-2", "user_id": "user-1", "day_number": 1, "step_index": 0},
    ]
    with pytest.raises(RuntimeError, match="Duplicate masterclass progress"):
        MIGRATION._stable_step_assignments(_payload(), duplicate)


def test_policy_payload_fails_closed_when_required_steps_are_missing():
    payload = _payload()
    payload["days"][0]["steps"] = [
        step for step in payload["days"][0]["steps"]
        if step["id"] != "day-01-messenger-link"
    ]
    with pytest.raises(RuntimeError, match="messenger step is missing"):
        MIGRATION._policy_v2_payload(payload)
