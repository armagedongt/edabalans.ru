"""Write a compact local readiness report for the authoring corpus."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import install_edabalans_writer_skill as writer_skill_installer

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


def voice_freshness(voice: Path) -> dict:
    folder = private(voice)
    memory = folder / "correction-memory.jsonl"
    semantic = folder / "semantic-report.json"
    state_path = folder / "analysis-state.json"
    index = folder / "voice-index.sqlite"
    errors: list[str] = []
    memory_count = len(rows(memory)) if memory.exists() else 0
    semantic_payload = json.loads(semantic.read_text(encoding="utf-8")) if semantic.exists() else {}
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    if not memory.exists():
        errors.append("correction-memory.jsonl is missing")
    if semantic_payload.get("correction_chains") != memory_count:
        errors.append("semantic-report correction_chains is stale")
    if state.get("correction_chains") != memory_count:
        errors.append("analysis-state correction_chains is stale")
    index_count = None
    index_check = "missing"
    if index.exists():
        try:
            with sqlite3.connect(index) as db:
                index_check = db.execute("PRAGMA quick_check").fetchone()[0]
                index_count = db.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
        except sqlite3.Error as exc:
            index_check = str(exc)
        if index_check != "ok":
            errors.append("voice index quick_check failed")
        if index_count != memory_count:
            errors.append("voice index corrections is stale")
    else:
        errors.append("voice-index.sqlite is missing")
    destination = writer_skill_installer.default_destination()
    skill = writer_skill_installer.sync_status(writer_skill_installer.SOURCE, destination)
    skill.update(writer_skill_installer.package_status(destination))
    if skill["status"] != "current" or skill.get("package_status") != "current":
        errors.append("installed edabalans-writer skill package is stale")
    return {
        "status": "current" if not errors else "stale",
        "errors": errors,
        "correction_memory": memory_count,
        "semantic_report": semantic_payload.get("correction_chains"),
        "analysis_state": state.get("correction_chains"),
        "index_corrections": index_count,
        "index_quick_check": index_check,
        "skill": skill,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    parser.add_argument("--voice", type=Path, required=True)
    parser.add_argument("--output", type=Path)
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
        "voice_freshness": voice_freshness(args.voice),
    }
    if args.output:
        output = private(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["voice_freshness"]["status"] == "stale" else 0


if __name__ == "__main__":
    raise SystemExit(main())
