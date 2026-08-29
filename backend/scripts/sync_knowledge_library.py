from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.knowledge_library_service import queue_review, save_relation, save_resource


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{line_no}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path.name}:{line_no}: object expected")
        rows.append(row)
    return rows


def load_bundle(root: Path) -> dict:
    resources = _jsonl(root / "resources.jsonl")
    relations = _jsonl(root / "relations.jsonl")
    reviews = _jsonl(root / "reviews.jsonl")
    keys = [row.get("resource_key") for row in resources]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise ValueError("resources.jsonl must contain unique resource_key values")
    canonical = json.dumps(
        {"resources": resources, "relations": relations, "reviews": reviews},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "resources": resources,
        "relations": relations,
        "reviews": reviews,
        "digest": hashlib.sha256(canonical).hexdigest(),
    }


def sync_bundle(
    root: Path,
    *,
    apply: bool = False,
    backup_confirmed: bool = False,
    expected_digest: str = "",
) -> dict:
    bundle = load_bundle(root)
    summary = {
        "resources": len(bundle["resources"]),
        "relations": len(bundle["relations"]),
        "reviews": len(bundle["reviews"]),
        "digest": bundle["digest"],
        "applied": False,
    }
    if not apply:
        return summary
    if not backup_confirmed:
        raise ValueError("--backup-confirmed is required for apply")
    if not expected_digest or expected_digest != bundle["digest"]:
        raise ValueError("bundle digest does not match --expected-digest")
    with SessionLocal() as db:
        try:
            for row in bundle["resources"]:
                save_resource(db, **row, commit=False)
            for row in bundle["relations"]:
                save_relation(db, **row, commit=False)
            for row in bundle["reviews"]:
                queue_review(db, **row, commit=False)
            db.commit()
        except Exception:
            db.rollback()
            raise
    summary["applied"] = True
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate or import a knowledge-library bundle")
    parser.add_argument("root", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    parser.add_argument("--expected-digest", default="")
    args = parser.parse_args()
    print(json.dumps(sync_bundle(
        args.root,
        apply=args.apply,
        backup_confirmed=args.backup_confirmed,
        expected_digest=args.expected_digest,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
