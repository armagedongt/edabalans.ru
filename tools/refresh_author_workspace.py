"""Rebuild all derived local authoring artifacts from private originals."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("authoring paths must be outside Git")
    return resolved


def run(script: str, *args: str) -> None:
    root = Path(__file__).resolve().parent
    subprocess.run([sys.executable, str(root / script), *args], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--working", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--voice", type=Path, required=True)
    args = parser.parse_args()
    originals = private(args.originals)
    working = private(args.working)
    index = private(args.index)
    voice = private(args.voice)
    run("build_author_working_corpus.py", "--originals", str(originals), "--working", str(working))
    run("build_author_catalog.py", "--working", str(working))
    run("tag_author_catalog.py", "--working", str(working))
    run("enrich_author_catalog.py", "--working", str(working))
    run("build_author_search_index.py", "--working", str(working), "--output", str(index))
    run("extract_author_rhetoric.py", "--working", str(working))
    run("extract_author_style_examples.py", "--working", str(working))
    run("select_voice_review_sample.py", "--working", str(working))
    run("build_voice_core.py", "--working", str(working))
    run("report_voice_core.py", "--working", str(working))
    run("verify_author_corpus.py", "--originals", str(originals), "--working", str(working))
    run("report_bot_processing.py", "--originals", str(originals), "--working", str(working))
    run(
        "report_author_corpus_health.py",
        "--working", str(working),
        "--voice", str(voice),
        "--output", str(working / "author-corpus-health.json"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
