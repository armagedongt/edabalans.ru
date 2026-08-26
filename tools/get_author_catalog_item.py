"""Print a full local content card and optionally its linked versions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("catalog path must be outside Git")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog_id")
    parser.add_argument("--working", type=Path, required=True)
    parser.add_argument("--with-related", action="store_true")
    args = parser.parse_args()
    working = private(args.working)
    cards = [json.loads(line) for line in (working / "author-content-tagged.jsonl").read_text(encoding="utf-8").splitlines() if line]
    by_id = {card["catalog_id"]: card for card in cards}
    card = by_id.get(args.catalog_id)
    if not card:
        raise SystemExit(f"card not found: {args.catalog_id}")
    result = {"card": card}
    if args.with_related:
        context = card.get("context") or {}
        ids = set(context.get("related_versions") or [])
        if context.get("duplicate_of"):
            ids.add(context["duplicate_of"])
        ids.update(
            other["catalog_id"] for other in cards
            if (other.get("context") or {}).get("duplicate_of") == card["catalog_id"]
        )
        ids.discard(card["catalog_id"])
        result["related_cards"] = [by_id[item] for item in sorted(ids) if item in by_id]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
