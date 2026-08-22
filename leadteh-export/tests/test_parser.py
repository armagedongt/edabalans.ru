from __future__ import annotations

from src.export import flatten_tree
from src.parser import normalize_scenario, text_to_markdown


def sample_payload():
    return {
        "data": {
            "id": 245278,
            "steps": [
                {
                    "id": 10,
                    "is_main": True,
                    "answer": {"type": "text", "value": "<b>Привет</b> <a href=\"https://example.test\">ссылка</a>"},
                    "x": 0,
                    "y": 0,
                    "next_step_id": 20,
                    "commands": [],
                    "tags": [],
                },
                {
                    "id": 20,
                    "answer": {"type": "condition", "conditions": [{"operator": "has_tag"}]},
                    "commands": [
                        {"id": 1, "text": "Да", "next_step_id": 30, "condition": {"value": "yes"}},
                        {"id": 2, "text": "Нет", "next_step_id": 40, "condition": {"value": "no"}},
                    ],
                },
                {"id": 30, "answer": {"type": "smart_delay", "smart_delay": {"days": "0", "hours": "12", "minutes": "0"}}, "next_step_id": 40},
                {"id": 40, "answer": {"type": "text", "value": "Конец"}, "next_step_id": None},
                {"id": 50, "answer": {"type": "text", "value": "Старая заготовка"}, "commands": []},
                {"id": 60, "answer": {"type": "text", "value": "Внешний вход"}, "commands": [{"text": "/start"}]},
                {"id": 70, "answer": {"type": "text", "value": "Detached A"}, "next_step_id": 80},
                {"id": 80, "answer": {"type": "text", "value": "Detached B"}},
            ],
        }
    }


def test_real_leadteh_fields_and_graph_classification():
    parsed = normalize_scenario(sample_payload(), {"id": 1969994, "name": "Выдача DQS", "parent_id": 2315015})
    assert parsed["scenario_id"] == 1969994
    assert len(parsed["blocks"]) == 8
    assert {(edge["from_block"], edge["to_block"]) for edge in parsed["edges"]} == {
        (10, 20), (20, 30), (20, 40), (30, 40), (70, 80)
    }
    blocks = {block["block_id"]: block for block in parsed["blocks"]}
    assert blocks[10]["classification"] == "main_flow"
    assert blocks[50]["classification"] == "orphan"
    assert blocks[60]["classification"] == "unknown_external_entry"
    assert blocks[70]["classification"] == "detached_component"
    assert parsed["unreachable_block_ids"] == [50, 60, 70, 80]
    assert next(edge for edge in parsed["edges"] if edge["from_block"] == 30)["delay_seconds"] == 43200
    assert "**Привет**" in text_to_markdown(blocks[10]["text_raw"])


def test_flat_tree_keeps_directories_but_the_export_can_filter_them():
    items = flatten_tree({"data": [{"id": 1, "type": "dir", "items": [{"id": 2, "type": "scheme"}]}]})
    assert [item["id"] for item in items] == [1, 2]
    assert items[1]["parent_id"] == 1
