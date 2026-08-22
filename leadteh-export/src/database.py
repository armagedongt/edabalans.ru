from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER, raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER, export_pass TEXT,
    status TEXT NOT NULL DEFAULT 'pending', error TEXT, block_count INTEGER DEFAULT 0,
    raw_file TEXT, parsed_file TEXT, updated_at TEXT, raw_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS blocks (
    scenario_id INTEGER NOT NULL, block_id TEXT NOT NULL, type TEXT, name TEXT,
    classification TEXT NOT NULL, component_id INTEGER, x REAL, y REAL, raw_json TEXT NOT NULL,
    PRIMARY KEY (scenario_id, block_id), FOREIGN KEY (scenario_id) REFERENCES scenarios(id)
);
CREATE TABLE IF NOT EXISTS edges (
    scenario_id INTEGER NOT NULL, from_block TEXT NOT NULL, to_block TEXT NOT NULL,
    delay_seconds TEXT, conditions_json TEXT NOT NULL, raw_json TEXT NOT NULL,
    PRIMARY KEY (scenario_id, from_block, to_block), FOREIGN KEY (scenario_id) REFERENCES scenarios(id)
);
CREATE TABLE IF NOT EXISTS texts (
    scenario_id INTEGER NOT NULL, block_id TEXT NOT NULL, text_raw TEXT, text_plain TEXT,
    html TEXT, markdown_file TEXT, classification TEXT NOT NULL,
    PRIMARY KEY (scenario_id, block_id), FOREIGN KEY (scenario_id, block_id) REFERENCES blocks(scenario_id, block_id)
);
CREATE TABLE IF NOT EXISTS links (scenario_id INTEGER, block_id TEXT, value TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS media (scenario_id INTEGER, block_id TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS tags (scenario_id INTEGER, block_id TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS variables (scenario_id INTEGER, block_id TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS conditions (scenario_id INTEGER, block_id TEXT, edge_to TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS export_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT, downloaded INTEGER DEFAULT 0, parsed INTEGER DEFAULT 0, errors INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_blocks_classification ON blocks(classification);
CREATE INDEX IF NOT EXISTS idx_scenarios_name ON scenarios(name);
CREATE INDEX IF NOT EXISTS idx_texts_plain ON texts(text_plain);
"""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArchiveDB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def start_run(self, mode: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO export_runs(mode, started_at) VALUES (?, ?)", (mode, _now())
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, downloaded: int, parsed: int, errors: int) -> None:
        self.connection.execute(
            "UPDATE export_runs SET finished_at=?, downloaded=?, parsed=?, errors=? WHERE id=?",
            (_now(), downloaded, parsed, errors, run_id),
        )
        self.connection.commit()

    def upsert_tree_item(self, item: dict[str, Any]) -> None:
        item_id = item.get("id")
        if not isinstance(item_id, int):
            return
        if item.get("type") == "dir":
            self.connection.execute(
                "INSERT INTO folders(id,name,parent_id,raw_json) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,parent_id=excluded.parent_id,raw_json=excluded.raw_json",
                (item_id, item.get("name"), item.get("parent_id"), _json(item)),
            )
        else:
            self.connection.execute(
                "INSERT INTO scenarios(id,name,parent_id,raw_json,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,parent_id=excluded.parent_id,raw_json=excluded.raw_json,updated_at=excluded.updated_at",
                (item_id, item.get("name"), item.get("parent_id"), _json(item), _now()),
            )
        self.connection.commit()

    def ensure_scenario(self, scenario_id: int, meta: dict[str, Any] | None = None) -> None:
        meta = meta or {"id": scenario_id}
        self.connection.execute(
            "INSERT INTO scenarios(id,name,parent_id,raw_json,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=COALESCE(excluded.name,scenarios.name), "
            "parent_id=COALESCE(excluded.parent_id,scenarios.parent_id),updated_at=excluded.updated_at",
            (scenario_id, meta.get("name"), meta.get("parent_id"), _json(meta), _now()),
        )
        self.connection.commit()

    def status(self, scenario_id: int) -> str | None:
        row = self.connection.execute("SELECT status FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
        return str(row["status"]) if row else None

    def mark(self, scenario_id: int, status: str, export_pass: str, error: str | None = None, raw_file: str | None = None, parsed_file: str | None = None, block_count: int | None = None) -> None:
        self.connection.execute(
            "UPDATE scenarios SET status=?,export_pass=?,error=?,raw_file=COALESCE(?,raw_file),"
            "parsed_file=COALESCE(?,parsed_file),block_count=COALESCE(?,block_count),updated_at=? WHERE id=?",
            (status, export_pass, error, raw_file, parsed_file, block_count, _now(), scenario_id),
        )
        self.connection.commit()

    def store_parsed(self, parsed: dict[str, Any], parsed_file: str) -> None:
        scenario_id = int(parsed["scenario_id"])
        for table in ("conditions", "variables", "tags", "media", "links", "texts", "edges", "blocks"):
            self.connection.execute(f"DELETE FROM {table} WHERE scenario_id=?", (scenario_id,))
        for block in parsed["blocks"]:
            block_id = str(block["block_id"])
            self.connection.execute(
                "INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?,?)",
                (scenario_id, block_id, block.get("type"), block.get("name"), block["classification"], block.get("component_id"), block.get("x"), block.get("y"), _json(block["raw"])),
            )
            if block.get("text_raw"):
                self.connection.execute(
                    "INSERT INTO texts VALUES(?,?,?,?,?,?,?)",
                    (scenario_id, block_id, block.get("text_raw"), block.get("text_plain"), block.get("html"), block.get("content_file"), block["classification"]),
                )
            for link in block.get("links", []):
                self.connection.execute("INSERT INTO links VALUES(?,?,?,?)", (scenario_id, block_id, str(link), _json(link)))
            for table, key in (("media", "media"), ("tags", "tags"), ("variables", "variables"), ("conditions", "conditions")):
                for value in block.get(key, []):
                    if table == "conditions":
                        self.connection.execute("INSERT INTO conditions VALUES(?,?,NULL,?)", (scenario_id, block_id, _json(value)))
                    else:
                        self.connection.execute(f"INSERT INTO {table} VALUES(?,?,?)", (scenario_id, block_id, _json(value)))
        for edge in parsed["edges"]:
            self.connection.execute(
                "INSERT INTO edges VALUES(?,?,?,?,?,?)",
                (scenario_id, str(edge["from_block"]), str(edge["to_block"]), None if edge.get("delay_seconds") is None else str(edge["delay_seconds"]), _json(edge.get("conditions", [])), _json(edge["raw"])),
            )
            for condition in edge.get("conditions", []):
                self.connection.execute(
                    "INSERT INTO conditions VALUES(?,?,?,?)",
                    (scenario_id, str(edge["from_block"]), str(edge["to_block"]), _json(condition)),
                )
        self.connection.execute(
            "UPDATE scenarios SET name=COALESCE(?,name),parent_id=COALESCE(?,parent_id),status='parsed',"
            "error=NULL,block_count=?,parsed_file=?,updated_at=? WHERE id=?",
            (parsed.get("scenario_name"), parsed.get("parent_id"), len(parsed["blocks"]), parsed_file, _now(), scenario_id),
        )
        self.connection.commit()

    def summary(self) -> dict[str, Any]:
        scalar = lambda sql: self.connection.execute(sql).fetchone()[0]
        scenarios = [dict(row) for row in self.connection.execute("SELECT id,name,status,export_pass,block_count,error FROM scenarios ORDER BY id")]
        return {
            "folders": scalar("SELECT COUNT(*) FROM folders"),
            "scenarios": scalar("SELECT COUNT(*) FROM scenarios"),
            "blocks": scalar("SELECT COUNT(*) FROM blocks"),
            "texts": scalar("SELECT COUNT(*) FROM texts"),
            "classifications": {row[0]: row[1] for row in self.connection.execute("SELECT classification,COUNT(*) FROM blocks GROUP BY classification")},
            "passes": {row[0]: row[1] for row in self.connection.execute("SELECT export_pass,COUNT(*) FROM scenarios WHERE status='parsed' GROUP BY export_pass")},
            "errors": [dict(row) for row in self.connection.execute("SELECT id,name,error FROM scenarios WHERE status='error'")],
            "scenario_rows": scenarios,
        }

    def content_rows(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(
            "SELECT t.scenario_id,s.name scenario_name,t.block_id,b.name block_name,t.classification,t.text_plain,t.markdown_file "
            "FROM texts t JOIN scenarios s ON s.id=t.scenario_id JOIN blocks b ON b.scenario_id=t.scenario_id AND b.block_id=t.block_id "
            "ORDER BY t.scenario_id,t.block_id"
        )]
