"""Append an owner correction chain to private memory and its local search index."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


REQUIRED = ("request", "assistant_draft", "owner_feedback", "owner_revision")


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("correction artifacts must stay outside Git")
    return resolved


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def record_payload(payload: dict, memory_path: Path, index_path: Path) -> dict:
    memory_path, index_path = map(private, (memory_path, index_path))
    missing = [field for field in REQUIRED if not str(payload.get(field) or "").strip()]
    if missing:
        raise ValueError(f"missing correction fields: {', '.join(missing)}")
    now = datetime.now(timezone.utc).isoformat()
    digest = hashlib.sha256(
        "\n".join(str(payload[field]) for field in REQUIRED).encode("utf-8")
    ).hexdigest()[:16]
    row = {
        "schema_version": "1.0",
        "analysis_version": "owner-correction-v1-20260826",
        "checkpoint": "owner_correction_recorded",
        "correction_id": payload.get("correction_id") or f"correction:{digest}",
        "title": payload.get("title") or "Правка владельца",
        "request": payload["request"],
        "retrieval_pack": payload.get("retrieval_pack"),
        "passport_version": payload.get("passport_version") or "voice-v1",
        "assistant_draft": payload["assistant_draft"],
        "assistant_versions": payload.get("assistant_versions") or [],
        "owner_feedback": payload["owner_feedback"],
        "owner_feedback_rounds": payload.get("owner_feedback_rounds") or [],
        "owner_revision": payload["owner_revision"],
        "owner_final": payload.get("owner_final") or payload["owner_revision"],
        "functional_explanation": payload.get("functional_explanation"),
        "candidate_rules": payload.get("candidate_rules") or [],
        "context": payload.get("context") or {},
        "status": payload.get("status") or "owner_correction_recorded",
        "captured_at": payload.get("captured_at") or now,
    }
    case_parts = [str(row["request"]), str(row["assistant_draft"])]
    case_parts.extend(str(value) for value in row["assistant_versions"])
    case_parts.append(str(row["owner_feedback"]))
    case_parts.extend(str(value) for value in row["owner_feedback_rounds"])
    case_parts.extend((str(row["owner_revision"]), str(row["owner_final"]), str(row.get("functional_explanation") or "")))
    row["full_case"] = "\n\n".join(part for part in case_parts if part)
    rows = {item["correction_id"]: item for item in read_jsonl(memory_path)}
    rows[row["correction_id"]] = row
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in rows.values()),
        encoding="utf-8",
    )
    with closing(sqlite3.connect(index_path)) as db:
        tables = {item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
        if not {"corrections", "voice_fts"}.issubset(tables):
            raise ValueError("voice index does not contain correction tables")
        db.execute(
            "INSERT OR REPLACE INTO corrections VALUES (?, ?)",
            (row["correction_id"], json.dumps(row, ensure_ascii=False)),
        )
        db.execute("DELETE FROM voice_fts WHERE kind = 'correction' AND item_id = ?", (row["correction_id"],))
        db.execute(
            "INSERT INTO voice_fts VALUES (?, ?, ?, ?, ?, ?)",
            (
                "correction", row["correction_id"], row["context"].get("catalog_id") or "",
                row["title"], row["full_case"], " ".join(row["candidate_rules"]),
            ),
        )
        db.commit()
    return {"status": "recorded", "correction_id": row["correction_id"], "memory": str(memory_path), "index": str(index_path)}


def record(input_path: Path, memory_path: Path, index_path: Path) -> dict:
    input_path = private(input_path)
    return record_payload(json.loads(input_path.read_text(encoding="utf-8")), memory_path, index_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="Private JSON correction payload")
    parser.add_argument("--memory", type=Path, required=True, help="Private correction-memory.jsonl")
    parser.add_argument("--index", type=Path, required=True, help="Private voice-index.sqlite")
    args = parser.parse_args()
    print(json.dumps(record(args.input, args.memory, args.index), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
