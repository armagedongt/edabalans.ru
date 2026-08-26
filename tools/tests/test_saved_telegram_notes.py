import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "analyze_saved_telegram_notes.py"
SPEC = importlib.util.spec_from_file_location("saved_notes", MODULE_PATH)
saved_notes = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(saved_notes)


def test_run_preserves_records_and_separates_external_and_ideas(tmp_path: Path) -> None:
    source = tmp_path / "result.json"
    source.write_text(json.dumps({"type": "saved_messages", "messages": [
        {"id": 1, "date": "2026-01-01T00:00:00", "from": "Sergey", "text": ["Похудение: ", {"type": "link", "text": "источник", "href": "https://example.test/source"}]},
        {"id": 2, "date": "2026-01-02T00:00:00", "from": "Sergey", "text": "Идея поста: как не срываться на сладкое"},
        {"id": 3, "date": "2026-01-03T00:00:00", "from": "Sergey", "text": "Чужая мысль", "forwarded_from": "Other"},
        {"id": 4, "date": "2026-01-04T00:00:00", "from": "Sergey", "text": "", "photo": "photo.jpg"},
        {"id": 5, "date": "2026-01-05T00:00:00", "from": "Sergey", "text": "", "poll": {"question": "Худеете летом?", "answers": ["Да", "Нет"]}},
        {"id": 6, "date": "2026-01-06T00:00:00", "from": "Sergey", "text": ""},
        {"id": 7, "date": "2026-01-07T00:00:00", "from": "Sergey", "text": "Длинный хук про питание и привычки\nПервый вариант про калории"},
        {"id": 8, "date": "2026-01-08T00:00:00", "from": "Sergey", "text": "Длинный хук про питание и привычки\nВторой вариант про калории"},
        {"id": 9, "date": "2026-01-09T00:00:00", "from": "Sergey", "text": "Продам ноутбук, вес 2.5 кг. Состояние отличное, пишите."},
    ]}, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "out"
    report = saved_notes.run(source, output)

    assert report["coverage_ok"] is True
    assert report["saved_cards"] == 8
    assert report["skipped_empty_or_service"] == 1
    external = [json.loads(line) for line in (output / "external-references.jsonl").read_text(encoding="utf-8").splitlines()]
    assert external[0]["message_id"] == 3
    ideas = [json.loads(line) for line in (output / "content-ideas.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(card["message_id"] == 2 for card in ideas)
    candidates = [json.loads(line) for line in (output / "author-relevant-candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(card["message_id"] == 2 for card in candidates)
    all_cards = [json.loads(line) for line in (output / "all-messages.jsonl").read_text(encoding="utf-8").splitlines()]
    assert next(card for card in all_cards if card["message_id"] == 1)["source_url"] == "https://example.test/source"
    assert next(card for card in all_cards if card["message_id"] == 5)["text_plain"] == "Худеете летом? Да Нет"
    first_variant = next(card for card in all_cards if card["message_id"] == 7)
    assert first_variant["variant_group"]
    assert first_variant["related_message_ids"] == [8]
    laptop = next(card for card in all_cards if card["message_id"] == 9)
    assert laptop["classification"] == "personal_or_off_topic"
    assert (output / "report.md").exists()
