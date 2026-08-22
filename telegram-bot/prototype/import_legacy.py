from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPO_ROOT / "leadteh-export" / "data" / "leadteh_archive.sqlite"
DEFAULT_DESTINATION = REPO_ROOT / "telegram-bot" / "runtime" / "catalog.sqlite"


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE archive_content_items (
    id TEXT PRIMARY KEY,
    source_system TEXT NOT NULL,
    source_scenario_id TEXT NOT NULL,
    source_block_id TEXT NOT NULL,
    scenario_name TEXT,
    block_name TEXT,
    classification TEXT,
    title TEXT NOT NULL,
    source_text TEXT NOT NULL DEFAULT '',
    plain_text TEXT NOT NULL DEFAULT '',
    source_format TEXT NOT NULL,
    media_kind TEXT,
    source_payload TEXT NOT NULL DEFAULT '{}',
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_system, source_scenario_id, source_block_id)
);

CREATE TABLE archive_media_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archive_content_item_id TEXT NOT NULL REFERENCES archive_content_items(id),
    media_kind TEXT NOT NULL,
    filename TEXT,
    mime_type TEXT,
    byte_size INTEGER,
    source_url TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE archive_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archive_content_item_id TEXT NOT NULL REFERENCES archive_content_items(id),
    value TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE content_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin_archive_item_id TEXT REFERENCES archive_content_items(id),
    title TEXT NOT NULL,
    body_source TEXT NOT NULL DEFAULT '',
    source_format TEXT NOT NULL DEFAULT 'leadteh_mixed',
    media_kind TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    version_no INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft'
);

CREATE TABLE sequence_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence_id INTEGER NOT NULL REFERENCES sequences(id),
    position INTEGER NOT NULL,
    kind TEXT NOT NULL,
    content_item_id INTEGER REFERENCES content_items(id),
    delay_seconds INTEGER,
    label TEXT,
    configuration TEXT NOT NULL DEFAULT '{}',
    UNIQUE (sequence_id, position)
);

CREATE TRIGGER archive_content_no_update
BEFORE UPDATE ON archive_content_items
BEGIN SELECT RAISE(ABORT, 'LeadTeh archive is immutable'); END;

CREATE TRIGGER archive_content_no_delete
BEFORE DELETE ON archive_content_items
BEGIN SELECT RAISE(ABORT, 'LeadTeh archive is immutable'); END;

CREATE TRIGGER archive_media_no_update
BEFORE UPDATE ON archive_media_assets
BEGIN SELECT RAISE(ABORT, 'LeadTeh archive is immutable'); END;

CREATE TRIGGER archive_media_no_delete
BEFORE DELETE ON archive_media_assets
BEGIN SELECT RAISE(ABORT, 'LeadTeh archive is immutable'); END;
"""


def stable_id(scenario_id: Any, block_id: Any) -> str:
    value = f"leadteh:{scenario_id}:{block_id}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:24]


def plain_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:b|strong|i|em|u|s|del|code|pre|blockquote)[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", r"\2 (\1)", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[([^]]+)]\((https?://[^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"(?<!\w)[*_~`](.+?)[*_~`](?!\w)", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def detect_format(value: str) -> str:
    if re.search(r"</?(?:b|strong|i|em|u|s|a|code|pre|blockquote|br)\b", value, re.IGNORECASE):
        return "leadteh_mixed"
    if re.search(r"(?:^|\s)[*_~`].+?[*_~`]", value, re.DOTALL) or re.search(r"\[[^]]+]\(https?://", value):
        return "markdown_v1"
    return "plain"


def make_title(block_name: str | None, scenario_name: str | None, body: str, media_kind: str | None) -> str:
    if block_name and block_name.strip():
        return block_name.strip()[:120]
    first_line = next((line.strip() for line in plain_text(body).splitlines() if line.strip()), "")
    if first_line:
        return first_line[:120]
    if media_kind:
        return f"{media_kind.capitalize()} из «{scenario_name or 'LeadTeh'}»"
    return scenario_name or "Сообщение LeadTeh"


def load_items(source: sqlite3.Connection) -> dict[tuple[str, str], dict[str, Any]]:
    source.row_factory = sqlite3.Row
    items: dict[tuple[str, str], dict[str, Any]] = {}
    query = """
        SELECT t.scenario_id, t.block_id, t.text_raw, t.text_plain, t.html,
               t.classification, s.name AS scenario_name, b.name AS block_name
        FROM texts t
        JOIN scenarios s ON s.id = t.scenario_id
        LEFT JOIN blocks b ON b.scenario_id = t.scenario_id AND b.block_id = t.block_id
    """
    for row in source.execute(query):
        key = (str(row["scenario_id"]), str(row["block_id"]))
        body = row["text_raw"] or row["html"] or row["text_plain"] or ""
        items[key] = {
            "scenario_id": key[0],
            "block_id": key[1],
            "scenario_name": row["scenario_name"],
            "block_name": row["block_name"],
            "classification": row["classification"],
            "body": body,
            "media": [],
            "links": [],
        }

    media_query = """
        SELECT m.scenario_id, m.block_id, m.raw_json, s.name AS scenario_name,
               b.name AS block_name, b.classification
        FROM media m
        JOIN scenarios s ON s.id = m.scenario_id
        LEFT JOIN blocks b ON b.scenario_id = m.scenario_id AND b.block_id = m.block_id
    """
    for row in source.execute(media_query):
        key = (str(row["scenario_id"]), str(row["block_id"]))
        payload = json.loads(row["raw_json"] or "{}")
        item = items.setdefault(
            key,
            {
                "scenario_id": key[0],
                "block_id": key[1],
                "scenario_name": row["scenario_name"],
                "block_name": row["block_name"],
                "classification": row["classification"],
                "body": payload.get("caption") or "",
                "media": [],
                "links": [],
            },
        )
        if not item["body"] and payload.get("caption"):
            item["body"] = payload["caption"]
        item["media"].append(payload)

    for row in source.execute("SELECT scenario_id, block_id, value, raw_json FROM links"):
        key = (str(row["scenario_id"]), str(row["block_id"]))
        if key in items and row["value"]:
            items[key]["links"].append({"value": row["value"], "raw_json": row["raw_json"]})
    return items


def build_catalog(source_path: Path = DEFAULT_SOURCE, destination_path: Path = DEFAULT_DESTINATION) -> dict[str, int]:
    if not source_path.exists():
        raise FileNotFoundError(f"LeadTeh archive not found: {source_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        destination_path.unlink()

    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(destination_path)
    try:
        destination.executescript(SCHEMA)
        items = load_items(source)
        media_count = 0
        link_count = 0
        for item in items.values():
            archive_id = stable_id(item["scenario_id"], item["block_id"])
            media_kind = item["media"][0].get("type") if item["media"] else None
            body = item["body"] or ""
            destination.execute(
                """
                INSERT INTO archive_content_items (
                    id, source_system, source_scenario_id, source_block_id,
                    scenario_name, block_name, classification, title, source_text,
                    plain_text, source_format, media_kind, source_payload
                ) VALUES (?, 'leadteh', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    archive_id,
                    item["scenario_id"],
                    item["block_id"],
                    item["scenario_name"],
                    item["block_name"],
                    item["classification"],
                    make_title(item["block_name"], item["scenario_name"], body, media_kind),
                    body,
                    plain_text(body),
                    detect_format(body),
                    media_kind,
                    json.dumps({"source": "leadteh_archive.sqlite"}, ensure_ascii=False),
                ),
            )
            for media in item["media"]:
                metadata = {key: value for key, value in media.items() if key not in {"url", "signature", "signature_fields"}}
                destination.execute(
                    """
                    INSERT INTO archive_media_assets (
                        archive_content_item_id, media_kind, filename, mime_type,
                        byte_size, source_url, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        archive_id,
                        media.get("type") or "media",
                        media.get("name"),
                        media.get("mime_type"),
                        media.get("size"),
                        media.get("url"),
                        json.dumps(metadata, ensure_ascii=False),
                    ),
                )
                media_count += 1
            for link in item["links"]:
                destination.execute(
                    "INSERT INTO archive_links (archive_content_item_id, value, payload) VALUES (?, ?, ?)",
                    (archive_id, link["value"], link["raw_json"] or "{}"),
                )
                link_count += 1

        # Это только наглядный черновик: выбор реальных рабочих постов владелец сделает позже.
        candidates = destination.execute(
            """
            SELECT id, title, source_text, source_format, media_kind
            FROM archive_content_items
            WHERE length(plain_text) > 80
            ORDER BY CASE WHEN media_kind IS NOT NULL THEN 0 ELSE 1 END, source_scenario_id, source_block_id
            LIMIT 3
            """
        ).fetchall()
        content_ids: list[int] = []
        for row in candidates:
            cursor = destination.execute(
                """
                INSERT INTO content_items (
                    origin_archive_item_id, title, body_source, source_format, media_kind
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (row[0], f"Демо-копия: {row[1]}", row[2], row[3], row[4]),
            )
            content_ids.append(int(cursor.lastrowid))

        sequence_id = destination.execute(
            "INSERT INTO sequences (code, name) VALUES ('masterclass-welcome-demo', 'Знакомство с мастер-классом — черновик')"
        ).lastrowid
        position = 1
        if content_ids:
            destination.execute(
                "INSERT INTO sequence_steps (sequence_id, position, kind, content_item_id, label) VALUES (?, ?, 'message', ?, 'Первое знакомство')",
                (sequence_id, position, content_ids[0]),
            )
            position += 1
        destination.execute(
            "INSERT INTO sequence_steps (sequence_id, position, kind, delay_seconds, label) VALUES (?, ?, 'delay', 86400, 'Подождать 24 часа')",
            (sequence_id, position),
        )
        position += 1
        if len(content_ids) > 1:
            destination.execute(
                "INSERT INTO sequence_steps (sequence_id, position, kind, content_item_id, label) VALUES (?, ?, 'message', ?, 'Польза и подход')",
                (sequence_id, position, content_ids[1]),
            )
            position += 1
        destination.execute(
            """
            INSERT INTO sequence_steps (sequence_id, position, kind, label, configuration)
            VALUES (?, ?, 'condition', 'Куплен мастер-класс?', '{"field":"has_product","product":"MASTERCLASS","branches":["yes","no"]}')
            """,
            (sequence_id, position),
        )
        position += 1
        if len(content_ids) > 2:
            destination.execute(
                "INSERT INTO sequence_steps (sequence_id, position, kind, content_item_id, label) VALUES (?, ?, 'message', ?, 'Ветка: ещё не купил')",
                (sequence_id, position, content_ids[2]),
            )
        destination.commit()
        return {
            "archive_items": len(items),
            "media_assets": media_count,
            "links": link_count,
            "demo_copies": len(content_ids),
        }
    finally:
        source.close()
        destination.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local Telegram content catalog from LeadTeh archive")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    result = build_catalog(args.source, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
