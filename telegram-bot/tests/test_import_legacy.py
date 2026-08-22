from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "prototype" / "import_legacy.py"
SPEC = importlib.util.spec_from_file_location("import_legacy", MODULE_PATH)
assert SPEC and SPEC.loader
IMPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORTER)


SOURCE_SCHEMA = """
CREATE TABLE scenarios (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE blocks (
    scenario_id INTEGER, block_id TEXT, name TEXT, classification TEXT,
    PRIMARY KEY (scenario_id, block_id)
);
CREATE TABLE texts (
    scenario_id INTEGER, block_id TEXT, text_raw TEXT, text_plain TEXT,
    html TEXT, classification TEXT
);
CREATE TABLE media (scenario_id INTEGER, block_id TEXT, raw_json TEXT);
CREATE TABLE links (scenario_id INTEGER, block_id TEXT, value TEXT, raw_json TEXT);
"""


class LegacyImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "source.sqlite"
        self.destination = root / "catalog.sqlite"
        connection = sqlite3.connect(self.source)
        connection.executescript(SOURCE_SCHEMA)
        connection.execute("INSERT INTO scenarios VALUES (10, 'Тестовый сценарий')")
        connection.execute("INSERT INTO blocks VALUES (10, '20', NULL, 'main_flow')")
        connection.execute(
            "INSERT INTO texts VALUES (10, '20', ?, ?, NULL, 'main_flow')",
            ("*Жирный текст* 😊 [ссылка](https://example.com)", "Жирный текст 😊 ссылка"),
        )
        connection.execute(
            "INSERT INTO media VALUES (10, '20', ?)",
            ('{"type":"video","name":"demo.mp4","mime_type":"video/mp4","size":123,"url":"https://example.com/video"}',),
        )
        connection.execute(
            "INSERT INTO links VALUES (10, '20', 'https://example.com', '{}')"
        )
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_import_preserves_markup_media_and_links(self) -> None:
        result = IMPORTER.build_catalog(self.source, self.destination)
        self.assertEqual(result["archive_items"], 1)
        self.assertEqual(result["media_assets"], 1)
        self.assertEqual(result["links"], 1)
        connection = sqlite3.connect(self.destination)
        row = connection.execute(
            "SELECT source_text, plain_text, source_format, media_kind FROM archive_content_items"
        ).fetchone()
        self.assertIn("*Жирный текст*", row[0])
        self.assertIn("😊", row[0])
        self.assertIn("https://example.com", row[0])
        self.assertEqual(row[2], "markdown_v1")
        self.assertEqual(row[3], "video")
        connection.close()

    def test_archive_rows_are_immutable(self) -> None:
        IMPORTER.build_catalog(self.source, self.destination)
        connection = sqlite3.connect(self.destination)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "archive is immutable"):
            connection.execute("UPDATE archive_content_items SET title = 'Изменено'")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "archive is immutable"):
            connection.execute("DELETE FROM archive_content_items")
        connection.close()

    def test_rebuild_is_repeatable(self) -> None:
        first = IMPORTER.build_catalog(self.source, self.destination)
        second = IMPORTER.build_catalog(self.source, self.destination)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
