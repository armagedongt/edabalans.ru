"""Verify that the private working catalog preserves every exported source record."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("corpus path must be outside Git")
    return resolved


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--working", type=Path, required=True)
    args = parser.parse_args()
    originals, working = private(args.originals), private(args.working)
    source_bot = rows(originals / "bot-constructor.jsonl")
    cards = rows(working / "author-content-cards.jsonl")
    source_codes = {item["code"] for item in source_bot}
    bot_cards = [card for card in cards if card["source"] == "bot_constructor"]
    card_codes = {card["catalog_id"] for card in bot_cards}
    duplicate_cards = [card for card in bot_cards if (card.get("context") or {}).get("duplicate_of")]
    missing_canonical = [
        card["catalog_id"] for card in duplicate_cards
        if (card.get("context") or {}).get("duplicate_of") not in card_codes
    ]
    ids = [card["catalog_id"] for card in cards]
    report = {
        "source_bot_records": len(source_bot),
        "catalog_bot_records": len(bot_cards),
        "missing_bot_codes": sorted(source_codes - card_codes),
        "unexpected_bot_codes": sorted(card_codes - source_codes),
        "duplicate_records": len(duplicate_cards),
        "duplicates_without_canonical": missing_canonical,
        "duplicate_catalog_ids": len(ids) - len(set(ids)),
    }
    ok = not report["missing_bot_codes"] and not report["unexpected_bot_codes"] and not missing_canonical and not report["duplicate_catalog_ids"]
    report["ok"] = ok
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
