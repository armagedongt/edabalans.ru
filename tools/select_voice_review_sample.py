"""Create a diverse, deterministic author-voice review sample from tagged cards."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


ROLES = ("myth_reframe", "practical_plan", "diagnostic_dialogue", "personal_story", "positioning_proof", "product_offer")


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("sample path must be outside Git")
    return resolved


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    parser.add_argument("--per-role", type=int, default=5)
    args = parser.parse_args()
    working = private(args.working)
    rng = random.Random(25082026)
    cards = [
        card for card in read_jsonl(working / "author-content-tagged.jsonl")
        if card["voice_reference_eligibility"] == "candidate" and 250 <= len(card["text_plain"]) <= 7000
    ]
    chosen: list[dict] = []
    chosen_ids: set[str] = set()
    for role in ROLES:
        pool = [card for card in cards if role in card["editorial_roles_auto"]]
        rng.shuffle(pool)
        added = 0
        for card in pool:
            if card["catalog_id"] not in chosen_ids:
                chosen.append(card)
                chosen_ids.add(card["catalog_id"])
                added += 1
            if added >= args.per_role:
                break
    output = working / "voice-review-sample.jsonl"
    output.write_text("".join(json.dumps(card, ensure_ascii=False, sort_keys=True) + "\n" for card in chosen), encoding="utf-8")
    print(json.dumps({"sample": str(output), "cards": len(chosen), "roles": list(ROLES)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
