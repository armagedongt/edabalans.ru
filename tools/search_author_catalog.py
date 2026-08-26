"""Search the local authoring index and print compact, source-linked results."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("index path must be outside Git")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--voice-only", action="store_true")
    parser.add_argument("--role", action="append", default=[], help="Editorial role to require; can be repeated")
    parser.add_argument("--source", action="append", default=[], help="Source to require; can be repeated")
    parser.add_argument("--include-nonprimary", action="store_true", help="Include exact duplicates and retained technical/context records")
    args = parser.parse_args()
    index = private(args.index)
    filters = ["c.voice_reference_eligibility = 'candidate'"] if args.voice_only else []
    if not args.include_nonprimary:
        filters.append("c.reuse_catalog = 'included'")
    params: list[object] = [args.query]
    for role in args.role:
        filters.append("c.roles_json LIKE ?")
        params.append(f'%"{role}"%')
    for source in args.source:
        filters.append("c.source = ?")
        params.append(source)
    clause = "AND " + " AND ".join(filters) if filters else ""
    sql = f"""
        SELECT c.catalog_id, c.source, c.source_url, c.published_at, c.headline,
               c.context_json, c.roles_json, c.voice_reference_eligibility,
               snippet(content_fts, 2, '[', ']', ' … ', 28) AS excerpt
        FROM content_fts
        JOIN content_cards AS c ON c.catalog_id = content_fts.catalog_id
        WHERE content_fts MATCH ? {clause}
        ORDER BY bm25(content_fts), c.published_at DESC
        LIMIT ?
    """
    with sqlite3.connect(index) as db:
        rows = db.execute(sql, (*params, args.limit)).fetchall()
    results = [
        {
            "catalog_id": row[0], "source": row[1], "source_url": row[2], "published_at": row[3],
            "headline": row[4], "context": json.loads(row[5]), "roles": json.loads(row[6]),
            "voice_reference_eligibility": row[7], "excerpt": row[8],
        }
        for row in rows
    ]
    print(json.dumps({"query": args.query, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
