"""Collect source-linked examples of recurring authorial moves for later retrieval."""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path


HTML = re.compile(r"<[^>]+>")
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("self_irony_or_colloquial_humor", re.compile(r"(?:ну вы поняли|\bкарл\b|\bхз\b|как два пальца|сгорел сарай|меркурий в ретрограде|колени[^.]{0,45}не каз[её]н|¯\\_|😂|😅|😄|😆|🤣)", re.I)),
    ("expected_objection", re.compile(r"(?:спросите вы|можно возразить|может показаться|а как же|внимание вопрос)", re.I)),
    ("contrast_or_reframe", re.compile(r"(?:не [^.?!]{2,90}, а [^.?!]{2,90}|вместо [^.?!]{2,90}, [^.?!]{2,90})", re.I)),
    ("reader_invitation", re.compile(r"(?:как вам такая идея|что думаете|делитесь в комментариях|колитесь|всех обнял)", re.I)),
]


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("catalog path must be outside Git")
    return resolved


def snippet(text: str, match: re.Match[str]) -> str:
    start, end = max(0, match.start() - 180), min(len(text), match.end() + 260)
    return text[start:end].strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    args = parser.parse_args()
    working = private(args.working)
    examples = []
    for line in (working / "author-content-tagged.jsonl").read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        card = json.loads(line)
        text = html.unescape(HTML.sub("", card.get("text_source") or ""))
        for kind, pattern in PATTERNS:
            match = pattern.search(text)
            if match:
                examples.append({
                    "catalog_id": card["catalog_id"],
                    "source": card["source"],
                    "source_url": card.get("source_url"),
                    "headline": card.get("headline"),
                    "roles": card.get("editorial_roles_auto") or [],
                    "style_move_auto": kind,
                    "matched_text": match.group(0),
                    "context_snippet": snippet(text, match),
                })
    output = working / "author-style-examples.jsonl"
    output.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in examples), encoding="utf-8")
    report = {"examples": len(examples), "by_move": dict(Counter(item["style_move_auto"] for item in examples))}
    (working / "author-style-examples-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
