import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "prepare_post_planning_handoff.py"
SPEC = importlib.util.spec_from_file_location("post_handoff", MODULE_PATH)
post_handoff = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(post_handoff)


def test_handoff_keeps_content_sources_and_only_content_tasks(tmp_path: Path) -> None:
    source = tmp_path / "editorial.jsonl"
    rows = [
        {"message_id": 1, "classification": "authored_ready_post", "editorial_kind": "post_or_substantial_draft", "text_plain": "Пост о питании"},
        {"message_id": 2, "classification": "nutrition_or_content_idea", "editorial_kind": "content_idea", "text_plain": "Идея про сладкое", "needs_review": True},
        {"message_id": 3, "classification": "authored_ready_post", "editorial_kind": "task_or_project", "text_plain": "Написать пост про бег"},
        {"message_id": 4, "classification": "personal_or_off_topic", "editorial_kind": "task_or_project", "text_plain": "Купить молоко"},
        {"message_id": 5, "classification": "external_reference", "editorial_kind": "reference", "text_plain": "Чужая ссылка"},
        {"message_id": 6, "classification": "technical_or_service", "editorial_kind": "task_or_project", "text_plain": "Написать пост для канала"},
    ]
    source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    output = tmp_path / "handoff"
    report = post_handoff.run(source, output)

    assert report["post_planning_source"] == 3
    assert report["old_content_tasks"] == 1
    assert report["needs_context"] == 1
    assert (output / "INSTRUCTIONS_FOR_POST_PLANNING_CHAT.md").exists()
