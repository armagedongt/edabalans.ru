"""Build a local SQLite full-text index for the private authoring catalog."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("index path must be outside Git")
    return resolved


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    working, output = private(args.working), private(args.output)
    enriched = working / "author-content-enriched.jsonl"
    tagged = working / "author-content-tagged.jsonl"
    cards = read_jsonl(enriched if enriched.exists() else tagged if tagged.exists() else working / "author-content-cards.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.executescript("""
            DROP TABLE IF EXISTS content_fts;
            DROP TABLE IF EXISTS content_cards;
            CREATE TABLE content_cards (
                catalog_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_url TEXT,
                published_at TEXT,
                headline TEXT,
                text_plain TEXT NOT NULL,
                context_json TEXT NOT NULL,
                media_json TEXT NOT NULL,
                signals_json TEXT NOT NULL,
                roles_json TEXT NOT NULL,
                reuse_catalog TEXT NOT NULL,
                voice_reference_eligibility TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE content_fts USING fts5(
                catalog_id UNINDEXED,
                headline,
                text_plain,
                scenario,
                roles,
                tokenize='unicode61 remove_diacritics 2'
            );
        """)
        for card in cards:
            context = card.get("context") or {}
            db.execute(
                "INSERT INTO content_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    card["catalog_id"], card["source"], card.get("source_url"), card.get("published_at"),
                    card.get("headline"), card.get("text_plain") or "", json.dumps(context, ensure_ascii=False),
                    json.dumps(card.get("media") or {}, ensure_ascii=False),
                    json.dumps(card.get("automatic_signals") or [], ensure_ascii=False),
                    json.dumps(card.get("editorial_roles_auto") or [], ensure_ascii=False), card["reuse_catalog"],
                    card["voice_reference_eligibility"],
                ),
            )
            db.execute(
                "INSERT INTO content_fts VALUES (?, ?, ?, ?, ?)",
                (card["catalog_id"], card.get("headline") or "", card.get("text_plain") or "", context.get("scenario") or "", " ".join(card.get("editorial_roles_auto") or [])),
            )
        db.execute("INSERT INTO content_fts(content_fts) VALUES ('optimize')")
        count = db.execute("SELECT count(*) FROM content_cards").fetchone()[0]
    print(json.dumps({"index": str(output), "cards": count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
