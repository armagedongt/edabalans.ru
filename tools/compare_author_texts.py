"""Compare a raw author source against a locally extracted Markdown rendition.

This is a diagnostic only: it never rewrites either source.  It helps the
content migration workflow decide whether the legacy HTML can be used as the
authoritative text or only as a source of visual structure and media.
"""

from __future__ import annotations

import argparse
import re
from difflib import SequenceMatcher
from pathlib import Path


def visible_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^\)]*\)", r"\1", text)
    text = re.sub(r"[`*_>#]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("legacy", type=Path)
    args = parser.parse_args()

    source = visible_markdown(args.source.read_text(encoding="utf-8"))
    legacy = visible_markdown(args.legacy.read_text(encoding="utf-8"))
    ratio = SequenceMatcher(None, source, legacy).ratio()
    print(f"source visible chars: {len(source)}")
    print(f"legacy visible chars: {len(legacy)}")
    print(f"sequence similarity: {ratio:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
