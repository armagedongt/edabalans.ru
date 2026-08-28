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
LEGACY_FIELDS = (
    ("source_artifacts", "Исходники и доказательства"),
    ("before_after_examples", "Примеры до и после"),
    ("positive_examples", "Положительные примеры"),
    ("negative_examples", "Отрицательные примеры"),
    ("application_examples", "Примеры применения"),
    ("legacy_full_cases", "Полные цепочки из прежней схемы"),
)


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


def render_legacy_field(label: str, value: object) -> str:
    if not value:
        return ""
    return f"{label}:\n{json.dumps(value, ensure_ascii=False, indent=2)}"


def merged_list(*values: object) -> list:
    result: list = []
    seen: set[str] = set()
    for value in values:
        value = value or []
        items = value if isinstance(value, list) else [value]
        for item in items:
            if item is None or item == "":
                continue
            fingerprint = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            result.append(item)
    return result


def complete_history(existing: dict, list_field: str, scalar_field: str, *incoming: object) -> list:
    history = existing.get(list_field) or []
    if existing and existing.get("schema_version") != "1.3":
        history = merged_list([existing.get(scalar_field)], history)
    return merged_list(history, *incoming)


def update_derived_correction_state(folder: Path, count: int, updated_at: str) -> None:
    report_path = folder / "semantic-report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["correction_chains"] = count
        report["corrections_updated_at"] = updated_at
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    state_path = folder / "analysis-state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["correction_chains"] = count
        state["corrections_updated_at"] = updated_at
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def record_payload(payload: dict, memory_path: Path, index_path: Path) -> dict:
    memory_path, index_path = map(private, (memory_path, index_path))
    missing = [field for field in REQUIRED if not str(payload.get(field) or "").strip()]
    if missing:
        raise ValueError(f"missing correction fields: {', '.join(missing)}")
    now = datetime.now(timezone.utc).isoformat()
    digest = hashlib.sha256(
        "\n".join(str(payload[field]) for field in REQUIRED).encode("utf-8")
    ).hexdigest()[:16]
    correction_id = payload.get("correction_id") or f"correction:{digest}"
    memory_existed = memory_path.exists()
    rows = {item["correction_id"]: item for item in read_jsonl(memory_path)}
    if not index_path.exists():
        raise ValueError(f"voice index does not exist: {index_path}")
    with closing(sqlite3.connect(index_path)) as db:
        tables = {item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
        if not {"corrections", "voice_fts"}.issubset(tables):
            raise ValueError("voice index does not contain correction tables")
        indexed_count = db.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
    if indexed_count and (not memory_existed or not rows):
        raise ValueError("refusing to reconcile a populated voice index with a missing or empty correction memory")
    existing = rows.get(correction_id) or {}
    existing_context = existing.get("context") if isinstance(existing.get("context"), dict) else {}
    incoming_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    next_owner_final = payload.get("owner_final") or existing.get("owner_final") or payload["owner_revision"]
    legacy_full_cases = merged_list(existing.get("legacy_full_cases"), payload.get("legacy_full_cases"))
    if existing and existing.get("schema_version") != "1.3" and existing.get("full_case"):
        legacy_full_cases = merged_list(legacy_full_cases, [existing["full_case"]])
    row = dict(existing)
    row.update({
        "schema_version": "1.3",
        "analysis_version": "owner-correction-v1.3-20260827",
        "checkpoint": "owner_correction_recorded",
        "correction_id": correction_id,
        "title": payload.get("title") or existing.get("title") or "Правка владельца",
        "request": payload["request"],
        "request_versions": complete_history(
            existing, "request_versions", "request", [payload["request"]], payload.get("request_versions")
        ),
        "retrieval_pack": payload.get("retrieval_pack", existing.get("retrieval_pack")),
        "passport_version": payload.get("passport_version") or existing.get("passport_version") or "voice-v1",
        "assistant_draft": payload["assistant_draft"],
        "assistant_versions": complete_history(
            existing, "assistant_versions", "assistant_draft",
            [payload["assistant_draft"]], payload.get("assistant_versions")
        ),
        "owner_feedback": payload["owner_feedback"],
        "owner_feedback_rounds": complete_history(
            existing, "owner_feedback_rounds", "owner_feedback",
            [payload["owner_feedback"]], payload.get("owner_feedback_rounds")
        ),
        "owner_revision": payload["owner_revision"],
        "owner_revision_rounds": complete_history(
            existing, "owner_revision_rounds", "owner_revision",
            [payload["owner_revision"]], payload.get("owner_revision_rounds")
        ),
        "owner_final": next_owner_final,
        "owner_final_versions": complete_history(
            existing, "owner_final_versions", "owner_final",
            [next_owner_final], payload.get("owner_final_versions")
        ),
        "functional_explanation": payload.get("functional_explanation", existing.get("functional_explanation")),
        "candidate_rules": merged_list(existing.get("candidate_rules"), payload.get("candidate_rules")),
        "context": {**existing_context, **incoming_context},
        "status": payload.get("status") or existing.get("status") or "owner_correction_recorded",
        "captured_at": payload.get("captured_at") or existing.get("captured_at") or now,
        "updated_at": now,
    })
    for field, _label in LEGACY_FIELDS:
        if field == "legacy_full_cases":
            row[field] = legacy_full_cases
        else:
            row[field] = merged_list(existing.get(field), payload.get(field))
    case_parts = [str(value) for value in row["request_versions"]]
    case_parts.extend(str(value) for value in row["assistant_versions"])
    case_parts.extend(str(value) for value in row["owner_feedback_rounds"])
    case_parts.extend(str(value) for value in row["owner_revision_rounds"])
    case_parts.extend(str(value) for value in row["owner_final_versions"])
    case_parts.append(str(row.get("functional_explanation") or ""))
    case_parts.extend(
        render_legacy_field(label, row[field])
        for field, label in LEGACY_FIELDS
    )
    known_fields = {
        "schema_version", "analysis_version", "checkpoint", "correction_id",
        "title", "request", "request_versions", "retrieval_pack", "passport_version",
        "assistant_draft", "assistant_versions", "owner_feedback",
        "owner_feedback_rounds", "owner_revision", "owner_revision_rounds",
        "owner_final", "owner_final_versions",
        "functional_explanation", "candidate_rules", "context", "status",
        "captured_at", "updated_at", "full_case", *(field for field, _ in LEGACY_FIELDS),
    }
    legacy_extras = {
        key: value for key, value in row.items()
        if key not in known_fields and value not in (None, "", [], {})
    }
    case_parts.append(render_legacy_field("Дополнительные legacy-поля", legacy_extras))
    row["full_case"] = "\n\n".join(part for part in case_parts if part)
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
        valid_ids = set(rows)
        indexed_ids = {item[0] for item in db.execute("SELECT correction_id FROM corrections")}
        fts_ids = {item[0] for item in db.execute("SELECT item_id FROM voice_fts WHERE kind = 'correction'")}
        for orphan_id in (indexed_ids | fts_ids) - valid_ids:
            db.execute("DELETE FROM corrections WHERE correction_id = ?", (orphan_id,))
            db.execute("DELETE FROM voice_fts WHERE kind = 'correction' AND item_id = ?", (orphan_id,))
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
    update_derived_correction_state(memory_path.parent, len(rows), now)
    return {"status": "recorded", "correction_id": row["correction_id"], "memory": str(memory_path), "index": str(index_path)}


def record(input_path: Path, memory_path: Path, index_path: Path) -> dict:
    input_path = private(input_path)
    return record_payload(json.loads(input_path.read_text(encoding="utf-8")), memory_path, index_path)


def synchronize_derived(memory_path: Path) -> dict:
    memory_path = private(memory_path)
    count = len(read_jsonl(memory_path))
    updated_at = datetime.now(timezone.utc).isoformat()
    update_derived_correction_state(memory_path.parent, count, updated_at)
    return {
        "status": "synchronized",
        "correction_chains": count,
        "folder": str(memory_path.parent),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--input", type=Path, help="Private JSON correction payload")
    action.add_argument("--sync-derived", action="store_true", help="Repair derived correction counters without adding a correction")
    parser.add_argument("--memory", type=Path, required=True, help="Private correction-memory.jsonl")
    parser.add_argument("--index", type=Path, help="Private voice-index.sqlite")
    args = parser.parse_args()
    if args.sync_derived:
        result = synchronize_derived(args.memory)
    else:
        if args.index is None:
            parser.error("--index is required with --input")
        result = record(args.input, args.memory, args.index)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
