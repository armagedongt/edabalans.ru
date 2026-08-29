"""Print Telegram/Pikabu candidates for the calorie-course source audit."""

from __future__ import annotations

import sqlite3
import sys
import argparse
from pathlib import Path


DB = Path(r"C:\private\edabalans-content-authoring\author-catalog.sqlite")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    if args.ids:
        placeholders = ", ".join("?" for _ in args.ids)
        rows = connection.execute(
            f"""
            SELECT catalog_id, source, published_at, headline, source_url, text_plain
            FROM content_cards
            WHERE catalog_id IN ({placeholders})
            ORDER BY published_at DESC
            """,
            args.ids,
        ).fetchall()
        for row in rows:
            print("\n" + "=" * 100)
            print(" | ".join(str(row[key] or "") for key in row.keys() if key != "text_plain"))
            text = row["text_plain"] or ""
            print(text if args.full else text[:1800])
        return
    rows = connection.execute(
        """
        SELECT catalog_id, source, published_at, headline, source_url
        FROM content_cards
        WHERE source IN ('telegram_channel', 'pikabu')
          AND (
            lower(coalesce(headline, '')) LIKE '%калори%'
            OR lower(text_plain) LIKE '%счит%калори%'
            OR lower(text_plain) LIKE '%учет%калори%'
            OR lower(text_plain) LIKE '%учёт%калори%'
            OR lower(coalesce(headline, '')) LIKE '%дефицит%'
            OR lower(coalesce(headline, '')) LIKE '%перекус%'
            OR lower(coalesce(headline, '')) LIKE '%метаболизм%'
            OR lower(coalesce(headline, '')) LIKE '%голод%'
            OR lower(coalesce(headline, '')) LIKE '%срыв%'
          )
        ORDER BY published_at DESC
        """
    ).fetchall()
    print(f"COUNT {len(rows)}")
    for row in rows:
        values = [row[key] or "" for key in row.keys()]
        print(" | ".join(str(value).replace("\n", " ") for value in values))


if __name__ == "__main__":
    main()
