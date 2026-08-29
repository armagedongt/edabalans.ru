"""Read-only helper for finding calorie/training materials in the private author catalog."""

from __future__ import annotations

import json
import sqlite3
import sys
import argparse
from pathlib import Path


DB = Path(r"C:\private\edabalans-content-authoring\author-catalog.sqlite")
SOURCES = {"telegram_channel", "pikabu"}
GROUPS = {
    "strength": ["силов", "мышц", "повторен", "подход", "отказ", "rpe", "rir", "прогресси"],
    "endurance": ["вынослив", "кардио", "бег", "пульс", "vo2", "интервал", "мощност"],
    "start_and_adherence": ["трениров", "начать", "брос", "мотивац", "диван", "лень", "регуляр"],
    "calories_and_activity": ["калори", "метабол", "энергобаланс", "дефицит", "шаг", "активност", "расход"],
}


def matched_groups(text: str) -> list[str]:
    haystack = text.casefold()
    return [name for name, needles in GROUPS.items() if any(needle in haystack for needle in needles)]


def group_score(text: str, group: str) -> int:
    haystack = text.casefold()
    return sum(haystack.count(needle) for needle in GROUPS[group])


def excerpt_around_match(text: str, group: str, radius: int = 350) -> str:
    clean = " ".join(text.split())
    folded = clean.casefold()
    positions = [folded.find(needle) for needle in GROUPS[group]]
    positions = [position for position in positions if position >= 0]
    start = max(0, (min(positions) if positions else 0) - radius)
    end = min(len(clean), start + radius * 2)
    return clean[start:end]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=sorted(GROUPS))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--headlines-only", action="store_true")
    args = parser.parse_args()
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT catalog_id, source, source_url, published_at, headline, text_plain,
               signals_json, roles_json, reuse_catalog
        FROM content_cards
        WHERE source IN ('telegram_channel', 'pikabu')
        ORDER BY published_at DESC
        """
    ).fetchall()

    hits_by_group: dict[str, list[dict[str, object]]] = {name: [] for name in GROUPS}
    for row in rows:
        combined = f"{row['headline'] or ''}\n{row['text_plain']}"
        groups = matched_groups(combined)
        if not groups:
            continue
        for group in groups:
            hits_by_group[group].append({
                "catalog_id": row["catalog_id"],
                "source": row["source"],
                "url": row["source_url"],
                "published_at": row["published_at"],
                "headline": row["headline"],
                "score": group_score(combined, group),
                "excerpt": excerpt_around_match(row["text_plain"], group),
                "signals": json.loads(row["signals_json"] or "{}"),
                "roles": json.loads(row["roles_json"] or "{}"),
                "reuse_catalog": row["reuse_catalog"],
            })

    selected = {args.group: hits_by_group[args.group]} if args.group else hits_by_group
    result = {
        group: sorted(items, key=lambda item: (item["score"], item["published_at"] or ""), reverse=True)[: args.limit]
        for group, items in selected.items()
    }
    if args.headlines_only:
        result = {
            group: [
                {
                    "catalog_id": item["catalog_id"],
                    "source": item["source"],
                    "published_at": item["published_at"],
                    "headline": item["headline"],
                    "score": item["score"],
                    "url": item["url"],
                }
                for item in items
            ]
            for group, items in result.items()
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
