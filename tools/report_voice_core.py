"""Report the makeup of the selected current voice core."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("corpus path must be outside Git")
    return resolved


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    args = parser.parse_args()
    working = private(args.working)
    core = read(working / "voice-core-v1.jsonl")
    report = {
        "core_cards": len(core),
        "sources": dict(Counter(card["source"] for card in core)),
        "media": dict(Counter(card["media"]["presence"] for card in core)),
        "selection_roles": dict(Counter(card["voice_core_selection_role"] for card in core)),
        "all_editorial_roles": dict(Counter(role for card in core for role in card.get("editorial_roles_auto", []))),
        "score_range": {"min": min(card["voice_core_score"] for card in core), "max": max(card["voice_core_score"] for card in core)},
    }
    (working / "voice-core-v1-health.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
