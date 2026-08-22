import json
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_tag_cleanup_plan_is_complete_and_owner_rules_are_present() -> None:
    plan = json.loads((STATIC / "leadteh_tag_plan.json").read_text(encoding="utf-8"))
    assert len(plan) == 397
    by_name = {item["current_name"]: item for item in plan}
    assert by_name["Первое посещение"]["action"] == "keep"
    assert by_name["МК Оплатил"]["action"] == "convert_payment"
    assert by_name["Посты: 30 растений"]["proposed_name"] == "Пост - 30 растений"
    assert by_name["Из Пикабу Новые"]["proposed_name"] == "Пикабу"


def test_variable_catalog_is_aggregate_only() -> None:
    variables = json.loads((STATIC / "leadteh_variables.json").read_text(encoding="utf-8"))
    assert len(variables) == 227
    assert all(set(item) <= {"index", "name", "filled", "distinct", "types", "category", "action", "reason"} for item in variables)
