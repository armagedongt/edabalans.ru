from __future__ import annotations

from src.database import ArchiveDB
from src.parser import normalize_scenario
from test_parser import sample_payload


def test_sqlite_contains_required_tables_and_parsed_data(tmp_path):
    db = ArchiveDB(tmp_path / "archive.sqlite")
    try:
        db.ensure_scenario(1969994, {"id": 1969994, "name": "Выдача DQS"})
        parsed = normalize_scenario(sample_payload(), {"id": 1969994, "name": "Выдача DQS"})
        for block in parsed["blocks"]:
            if block.get("text_raw"):
                block["content_file"] = f"content/1969994/block_{block['block_id']}.md"
        db.store_parsed(parsed, "parsed/scenarios/1969994.json")
        summary = db.summary()
        assert summary["blocks"] == 8
        assert summary["texts"] == 6
        tables = {row[0] for row in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"folders", "scenarios", "blocks", "edges", "texts", "links", "media", "tags", "variables", "conditions", "export_runs"} <= tables
    finally:
        db.close()
