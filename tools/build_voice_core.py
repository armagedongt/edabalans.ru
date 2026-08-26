"""Select a diverse, source-linked core set for the current author voice model."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


# Personal stories are selected first so a more common role cannot consume them.
CORE_ROLES = ("personal_story", "positioning_proof", "myth_reframe", "diagnostic_dialogue", "practical_plan", "product_offer")


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("catalog path must be outside Git")
    return resolved


def score(card: dict) -> int:
    text_len = len(card.get("text_plain") or "")
    roles = set(card.get("editorial_roles_auto") or [])
    value = 0
    value += 3 if 500 <= text_len <= 5000 else 1 if text_len >= 300 else 0
    value += 2 * len(roles.intersection(CORE_ROLES))
    value += len(set(card.get("automatic_signals") or []))
    value += 1 if card["source"] == "telegram_channel" else 0
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    parser.add_argument("--telegram-per-role", type=int, default=12)
    parser.add_argument("--bot-per-role", type=int, default=6)
    args = parser.parse_args()
    working = private(args.working)
    cards = [json.loads(line) for line in (working / "author-content-enriched.jsonl").read_text(encoding="utf-8").splitlines() if line]
    pool = [card for card in cards if card["voice_use_status"] == "eligible_for_core_selection" and len(card.get("text_plain") or "") >= 300]
    selected: list[dict] = []
    seen: set[str] = set()
    for role in CORE_ROLES:
        for source, quota in (("telegram_channel", args.telegram_per_role), ("bot_constructor", args.bot_per_role)):
            ranked = sorted(
                (card for card in pool if card["source"] == source and role in card.get("editorial_roles_auto", [])),
                key=lambda card: (-score(card), card["catalog_id"]),
            )
            count = 0
            for card in ranked:
                if card["catalog_id"] in seen:
                    continue
                selected.append({**card, "voice_core_score": score(card), "voice_core_selection_role": role})
                seen.add(card["catalog_id"])
                count += 1
                if count == quota:
                    break
    output = working / "voice-core-v1.jsonl"
    output.write_text("".join(json.dumps(card, ensure_ascii=False, sort_keys=True) + "\n" for card in selected), encoding="utf-8")
    report = {
        "cards": len(selected),
        "selection_roles": dict(Counter(card["voice_core_selection_role"] for card in selected)),
        "sources": dict(Counter(card["source"] for card in selected)),
        "primary_functions": dict(Counter(card["catalog_primary_function_auto"] for card in selected)),
    }
    (working / "voice-core-v1-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
