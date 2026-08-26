"""Extract reusable hooks and endings from tagged content without changing texts."""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path


SENTENCE = re.compile(r"(?<=[.!?])\s+")
CTA = re.compile(r"\b(жмите|нажимайте|читайте|переходите|открывайте|пишите|задавайте|приходите|забирайте|подписывайтесь|делитесь|колитесь)\b", re.I)
TEASER = re.compile(r"\b(следующ\w* пост\w*|подробност\w*.*пост\w*|покажу|расскажу.*дальше)\b", re.I)
PROMPT = re.compile(r"\b(как вам|что думаете|кто|делитесь|колитесь|вопрос)\b", re.I)
HTML = re.compile(r"<[^>]+>")


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("catalog path must be outside Git")
    return resolved


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def hook_kind(headline: str) -> str:
    if "?" in headline:
        return "question"
    if re.search(r"\d", headline):
        return "number_or_specificity"
    if re.search(r"\b(я|моя|мне|мы)\b", headline, re.I):
        return "personal_entry"
    if re.search(r"\b(не|плох|ошибк|вредн|почему)\b", headline, re.I):
        return "contrarian_or_problem"
    return "statement_or_story"


def ending(text: str) -> str:
    paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
    if not paragraphs:
        return ""
    return paragraphs[-1][-700:]


def visible_with_paragraphs(value: str) -> str:
    return html.unescape(HTML.sub("", value)).strip()


def closing_kind(value: str) -> str:
    if CTA.search(value):
        return "direct_cta"
    if TEASER.search(value):
        return "next_step_teaser"
    if PROMPT.search(value) or "?" in value:
        return "conversation_prompt"
    return "conclusion_or_open_end"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    args = parser.parse_args()
    working = private(args.working)
    fragments = []
    for card in read_jsonl(working / "author-content-tagged.jsonl"):
        headline = card.get("headline") or ""
        text = visible_with_paragraphs(card.get("text_source") or "")
        closing = ending(text)
        if not headline and not text:
            continue
        fragments.append({
            "catalog_id": card["catalog_id"],
            "source": card["source"],
            "source_url": card.get("source_url"),
            "roles": card["editorial_roles_auto"],
            "voice_reference_eligibility": card["voice_reference_eligibility"],
            "hook": headline or SENTENCE.split(text)[0][:300],
            "hook_kind_auto": hook_kind(headline or text),
            "closing": closing,
            "closing_kind_auto": closing_kind(closing),
            "related_versions": (card.get("context") or {}).get("related_versions") or [],
        })
    output = working / "author-rhetoric-fragments.jsonl"
    output.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in fragments), encoding="utf-8")
    report = {
        "fragments": len(fragments),
        "hook_kinds": dict(Counter(item["hook_kind_auto"] for item in fragments)),
        "closing_kinds": dict(Counter(item["closing_kind_auto"] for item in fragments)),
    }
    (working / "author-rhetoric-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
