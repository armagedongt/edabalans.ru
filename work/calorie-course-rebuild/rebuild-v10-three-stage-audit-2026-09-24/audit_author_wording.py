#!/usr/bin/env python3
"""Measure verbatim author-source coverage in the calorie-course drafts.

The primary metric marks a draft token as author-source wording when it belongs
to an exact six-token sequence present in one original Tilda lesson or one
course transcript. Normalization ignores case, ё/е and Markdown punctuation,
but does not stem words or compare meaning. This deliberately does not reward
AI paraphrase that merely preserves the idea.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[-–—][0-9A-Za-zА-Яа-яЁё]+)*")
LINK_RE = re.compile(r"!?(\[[^\]]*\])\([^)]*\)")
HTML_RE = re.compile(r"<[^>]+>")


def visible_markdown(text: str) -> str:
    text = LINK_RE.sub(lambda match: match.group(1)[1:-1], text)
    text = HTML_RE.sub(" ", text)
    text = re.sub(r"^\s*:::.*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"[`*_>#|]", " ", text)
    return text


def tokens(text: str) -> list[str]:
    return [match.group(0).lower().replace("ё", "е") for match in TOKEN_RE.finditer(visible_markdown(text))]


def paragraphs(text: str) -> list[str]:
    result: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block or block.startswith("![") or block.startswith(":::source"):
            continue
        result.append(block)
    return result


def coverage(draft_tokens: list[str], index: set[tuple[str, ...]], n: int) -> tuple[int, list[bool]]:
    marked = [False] * len(draft_tokens)
    for start in range(max(0, len(draft_tokens) - n + 1)):
        if tuple(draft_tokens[start : start + n]) in index:
            for pos in range(start, start + n):
                marked[pos] = True
    return sum(marked), marked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_paths = sorted((args.repo / "work/calorie-course-rebuild/source-tilda-complete/lessons").glob("*/source.md"))
    source_paths += sorted((args.repo / "content/calories/reference/transcripts").glob("*.txt"))

    source_token_sets: dict[Path, list[str]] = {}
    indexes: dict[int, set[tuple[str, ...]]] = {n: set() for n in (4, 6, 10)}
    source_for_sixgram: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for path in source_paths:
        source_tokens = tokens(path.read_text(encoding="utf-8"))
        source_token_sets[path] = source_tokens
        for n in indexes:
            for start in range(max(0, len(source_tokens) - n + 1)):
                gram = tuple(source_tokens[start : start + n])
                indexes[n].add(gram)
                if n == 6:
                    source_for_sixgram[gram].add(path.relative_to(args.repo).as_posix())

    material_paths = sorted(
        path
        for module_dir in args.package.glob("module-*")
        for path in module_dir.rglob("*.md")
        if path.name != "source-use-notes.md"
    )

    materials = []
    corpus_total = 0
    corpus_exact = 0
    for path in material_paths:
        text = path.read_text(encoding="utf-8")
        draft_tokens = tokens(text)
        counts = {}
        marked_by_n = {}
        for n in indexes:
            matched, marked = coverage(draft_tokens, indexes[n], n)
            counts[str(n)] = {
                "matched_tokens": matched,
                "coverage_percent": round(100 * matched / len(draft_tokens), 1) if draft_tokens else 0,
            }
            marked_by_n[n] = marked

        primary_sources: dict[str, int] = defaultdict(int)
        for start in range(max(0, len(draft_tokens) - 6 + 1)):
            gram = tuple(draft_tokens[start : start + 6])
            for source in source_for_sixgram.get(gram, ()):
                primary_sources[source] += 1

        paragraph_rows = []
        for number, paragraph in enumerate(paragraphs(text), start=1):
            paragraph_tokens = tokens(paragraph)
            if len(paragraph_tokens) < 6:
                continue
            matched, _ = coverage(paragraph_tokens, indexes[6], 6)
            paragraph_rows.append(
                {
                    "paragraph": number,
                    "tokens": len(paragraph_tokens),
                    "coverage_percent": round(100 * matched / len(paragraph_tokens), 1),
                    "excerpt": " ".join(paragraph.split())[:220],
                }
            )

        primary_matched = counts["6"]["matched_tokens"]
        corpus_total += len(draft_tokens)
        corpus_exact += primary_matched
        materials.append(
            {
                "path": path.relative_to(args.repo).as_posix(),
                "tokens": len(draft_tokens),
                "coverage": counts,
                "paragraphs_total": len(paragraph_rows),
                "paragraphs_without_exact_sixgram": sum(row["coverage_percent"] == 0 for row in paragraph_rows),
                "lowest_coverage_paragraphs": sorted(paragraph_rows, key=lambda row: (row["coverage_percent"], -row["tokens"]))[:8],
                "top_matching_sources": [
                    {"path": source, "matching_sixgrams": count}
                    for source, count in sorted(primary_sources.items(), key=lambda item: item[1], reverse=True)[:5]
                ],
            }
        )

    result = {
        "metric": {
            "primary": "Exact normalized six-token sequences found in original Tilda lessons or course transcripts",
            "normalization": "case and е/ё normalized; Markdown punctuation and link targets ignored; no stemming or semantic matching",
            "interpretation": "Conservative evidence of verbatim author wording. It intentionally gives no credit to semantic paraphrase.",
        },
        "source_files": [path.relative_to(args.repo).as_posix() for path in source_paths],
        "course": {
            "tokens": corpus_total,
            "exact_sixgram_tokens": corpus_exact,
            "coverage_percent": round(100 * corpus_exact / corpus_total, 1) if corpus_total else 0,
        },
        "materials": materials,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
