"""Report reversible cleanup and editorial coverage for the bot archive."""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("corpus path must be outside Git")
    return resolved


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def normalized(value: str) -> str:
    return " ".join((value or "").lower().split())


def near_versions(candidates: list[dict]) -> dict:
    """Count retained same-title variants with 80–99% body similarity; never dedupe them."""
    by_title: dict[str, list[dict]] = defaultdict(list)
    for item in candidates:
        by_title[normalized(item.get("title") or "")].append(item)
    pairs = []
    involved: set[str] = set()
    for title, items in by_title.items():
        if not title or len(items) < 2:
            continue
        for left, right in combinations(items, 2):
            ratio = difflib.SequenceMatcher(None, normalized(left.get("body_source") or ""), normalized(right.get("body_source") or "")).ratio()
            if 0.80 <= ratio < 0.999:
                pairs.append({"left": left["code"], "right": right["code"], "similarity": round(ratio, 3), "title": left.get("title")})
                involved.update((left["code"], right["code"]))
    return {"near_duplicate_pairs": len(pairs), "retained_near_version_cards": len(involved), "examples": pairs[:10]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--working", type=Path, required=True)
    args = parser.parse_args()
    originals, working = private(args.originals), private(args.working)
    source = rows(originals / "bot-constructor.jsonl")
    candidates = rows(working / "bot-candidates.jsonl")
    excluded = rows(working / "bot-excluded.jsonl")
    enriched = [card for card in rows(working / "author-content-enriched.jsonl") if card["source"] == "bot_constructor"]
    templates = rows(originals / "bot-templates.jsonl")
    report = {
        "archive_records": len(source),
        "templates_kept_separate": len(templates),
        "main_working_pool": len(candidates),
        "retained_in_full_catalog": len(enriched),
        "excluded_from_default_results_not_deleted": dict(Counter(item["exclusion_reason"] for item in excluded)),
        "retained_near_versions": near_versions(candidates),
        "catalog_primary_functions": dict(Counter(card["catalog_primary_function_auto"] for card in enriched)),
        "editorial_roles_inclusive": dict(Counter(role for card in enriched for role in card.get("editorial_roles_auto", []))),
        "voice_use": dict(Counter(card["voice_reference_eligibility"] for card in enriched)),
        "media": dict(Counter(card["media"]["presence"] for card in enriched)),
        "semantic_review_required": sum(card["catalog_processing_status"] == "needs_semantic_review" for card in enriched),
    }
    output = working / "bot-processing-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
