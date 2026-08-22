from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.content_service import import_pikabu_items, normalized_payload
from app.database import SessionLocal


def load_rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("expected a JSON array or an object with an items array")
    return rows


def inspect_rows(rows: list[dict]) -> dict:
    summary = {"discovered": len(rows), "valid": 0, "failed": 0, "media_urls": 0, "links": 0}
    errors = []
    for row in rows:
        try:
            item = normalized_payload(row)
            summary["valid"] += 1
            summary["media_urls"] += len(item["media"])
            summary["links"] += len(item["links"])
        except (TypeError, ValueError) as exc:
            summary["failed"] += 1
            errors.append({"external_id": row.get("external_id"), "error": str(exc)})
    return {**summary, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or import a Pikabu browser export")
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write validated rows to PostgreSQL")
    parser.add_argument(
        "--backup-confirmed",
        action="store_true",
        help="Confirm that the production backup/restore check was completed",
    )
    args = parser.parse_args()
    rows = load_rows(args.json_path)
    inspected = inspect_rows(rows)
    print(json.dumps(inspected, ensure_ascii=False, indent=2))
    if not args.apply:
        return 0 if not inspected["failed"] else 2
    if not args.backup_confirmed:
        parser.error("--apply requires --backup-confirmed")
    with SessionLocal() as db:
        result = import_pikabu_items(db, rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
