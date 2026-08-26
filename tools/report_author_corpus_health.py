"""Write a compact local readiness report for the authoring corpus."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
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


def date_range(items: list[dict]) -> dict | None:
    dates = sorted(value for item in items if (value := item.get("published_at")))
    return {"from": dates[0], "to": dates[-1]} if dates else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    args = parser.parse_args()
    working = private(args.working)
    enriched = working / "author-content-enriched.jsonl"
    cards = rows(enriched if enriched.exists() else working / "author-content-tagged.jsonl")
    by_source = {source: [card for card in cards if card["source"] == source] for source in sorted({card["source"] for card in cards})}
    deferred = [
        "Pikabu: запускать только по отдельной ночной команде владельца",
        "личные заметочные Telegram-каналы: подключаются после базового корпуса",
        "видео-расшифровки: подключаются отдельным разговорным слоем",
    ]
    if "tilda_site" not in by_source:
        deferred.insert(1, "Tilda и продуктовый бриф: ожидают предоставления источника")
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "records": len(cards),
        "sources": {
            source: {
                "records": len(items),
                "date_range": date_range(items) if source != "bot_constructor" else None,
                "date_note": "Даты archive_copy отражают импорт в production, а не исходную публикацию." if source == "bot_constructor" else None,
            }
            for source, items in by_source.items()
        },
        "reuse_status": dict(Counter(card["reuse_catalog"] for card in cards)),
        "working_catalog_records": sum(card["reuse_catalog"] == "included" for card in cards),
        "retained_context_records": sum(card["reuse_catalog"] != "included" for card in cards),
        "voice_status": dict(Counter(card["voice_reference_eligibility"] for card in cards)),
        "media_status": dict(Counter(card["media"]["presence"] for card in cards)),
        "editorial_tag_status": dict(Counter(card["editorial_tag_confidence"] for card in cards)),
        "next_review": {
            "media_context_required": sum(card["text_usability"] == "media_context_required" for card in cards),
            "automatic_tags_to_review": sum(card["editorial_tag_confidence"] == "review_required" for card in cards),
            "exact_duplicates_retained": sum(card["reuse_catalog"] == "linked_duplicate" for card in cards),
        },
        "ready": [
            "поиск по исходным текстам и месту в сценарии",
            "поиск по первичным жанрам и связанным версиям",
            "выбор примеров для паспорта голоса",
            "каталог хуков и видов финалов",
        ],
        "deferred_or_missing": deferred,
    }
    output = working / "author-corpus-health.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
