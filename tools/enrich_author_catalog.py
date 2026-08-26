"""Turn multi-label editorial hints into a reversible dominant catalog function."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


PRIORITY = (
    "service_operation",
    "sequence_navigation",
    "welcome_or_onboarding",
    "calculator_or_form_step",
    "subscription_or_update_notice",
    "reference_link_or_content_handoff",
    "live_event_or_availability_notice",
    "micro_ui_marker",
    "media_dependent_reference",
    "short_media_prompt",
    "garbage_or_placeholder",
    "short_context_fragment",
    "teaser_or_bridge",
    "diagnostic_dialogue",
    "personal_story",
    "myth_reframe",
    "practical_plan",
    "positioning_proof",
    "product_offer",
    "announcement_or_reengagement",
    "educational_explanation",
)


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("catalog path must be outside Git")
    return resolved


def dominant_role(card: dict) -> str:
    roles = card.get("editorial_roles_auto") or []
    # A long instructional text with a product link should remain discoverable as
    # education first; a short product screen remains a product offer.
    if "product_offer" in roles and len(card.get("text_plain") or "") < 700:
        return "product_offer"
    return next((role for role in PRIORITY if role in roles), "unclassified_review")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    args = parser.parse_args()
    working = private(args.working)
    cards = []
    for line in (working / "author-content-tagged.jsonl").read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        card = json.loads(line)
        primary = dominant_role(card)
        voice_status = card["voice_reference_eligibility"]
        cards.append({
            **card,
            "catalog_primary_function_auto": primary,
            "catalog_processing_status": "ready" if primary != "unclassified_review" else "needs_semantic_review",
            "voice_use_status": "eligible_for_core_selection" if voice_status == "candidate" else "retained_not_default",
        })
    output = working / "author-content-enriched.jsonl"
    output.write_text("".join(json.dumps(card, ensure_ascii=False, sort_keys=True) + "\n" for card in cards), encoding="utf-8")
    report = {
        "cards": len(cards),
        "primary_functions": dict(Counter(card["catalog_primary_function_auto"] for card in cards)),
        "processing_status": dict(Counter(card["catalog_processing_status"] for card in cards)),
    }
    (working / "author-content-enriched-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
