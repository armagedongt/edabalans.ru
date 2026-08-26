import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "catalog_saved_notes_editorially.py"
SPEC = importlib.util.spec_from_file_location("editorial_notes", MODULE_PATH)
editorial_notes = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(editorial_notes)


def test_editorial_layer_separates_tasks_posts_and_references(tmp_path: Path) -> None:
    source = tmp_path / "all.jsonl"
    rows = [
        {"message_id": 1, "classification": "authored_ready_post", "text_plain": "Похудение без запретов. " * 50, "needs_review": True},
        {"message_id": 2, "classification": "authored_ready_post", "text_plain": "1. Написать пост про питание\n2. Запустить рекламу\n3. Собрать контент-план"},
        {"message_id": 3, "classification": "external_reference", "text_plain": "Чужой пост"},
        {"message_id": 4, "classification": "nutrition_or_content_idea", "text_plain": "Идея: почему тянет на сладкое"},
        {"message_id": 5, "classification": "unknown_review", "text_plain": ""},
        {"message_id": 6, "classification": "authored_ready_post", "text_plain": "Как сделать тренировку регулярной и написать план для себя. " * 80},
    ]
    source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    output = tmp_path / "editorial"
    report = editorial_notes.run(source, output)

    assert report["by_editorial_kind"]["post_or_substantial_draft"] == 2
    assert report["by_editorial_kind"]["task_or_project"] == 1
    assert report["by_editorial_kind"]["reference"] == 1
    assert report["by_editorial_kind"]["content_idea"] == 1
    assert report["by_editorial_kind"]["needs_triage"] == 1
    triage = [json.loads(line) for line in (output / "needs-human-triage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["message_id"] for row in triage] == [1]
    assert (output / "EDITORIAL_CATALOG_GUIDE.md").exists()
    assert (output / "posts-and-substantial-drafts.md").exists()
