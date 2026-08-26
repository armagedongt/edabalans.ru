"""Materialize reviewed private voice artifacts from source-linked safe configs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from build_author_voice import artifacts_ready, fragment_kind, paragraphs, private, visible_text


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCHEMA_VERSION = "1.0"
MATERIALIZATION_VERSION = "voice-semantic-v1-20260826-r9"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def combined_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    digest.update(MATERIALIZATION_VERSION.encode("utf-8"))
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def materialization_state_is_current(state: dict, digest: str) -> bool:
    return (
        state.get("materialization_sha256") == digest
        and state.get("materialization_version") == MATERIALIZATION_VERSION
        and state.get("checkpoint") == "semantic_materialization_complete"
    )


def stamp(rows: list[dict], *, created_at: str, input_digest: str) -> list[dict]:
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "analysis_version": MATERIALIZATION_VERSION,
        "materialized_at": created_at,
        "input_digest": input_digest,
        "checkpoint": "semantic_materialization_complete",
    }
    return [{**row, **metadata} for row in rows]


def split_case(markdown: str) -> dict:
    sections: dict[str, list[str]] = {}
    current = "header"
    for line in markdown.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        else:
            sections.setdefault(current, []).append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def excerpt(text: str) -> str:
    text = visible_text(text)
    if len(text) <= 900:
        return text
    return f"{text[:600]}\n…\n{text[-260:]}"


def corpus_usability(text: str) -> str:
    """Keep technical bot templates searchable without feeding them to the writer."""
    if re.search(r"\{\{[^{}]+\}\}|\$(?:[A-Za-zА-Яа-яЁё_][\w]*|\d+_[\w]+)", text):
        return "technical_template"
    return "author_text"


def evidence_item(evidence_id: str, rule: dict, by_id: dict[str, dict]) -> dict:
    """Resolve catalog examples and direct owner decisions through one evidence contract."""
    if evidence_id == "case:cutlets":
        return {
            "catalog_id": evidence_id,
            "source": "correction_case",
            "headline": "Кейс о котлетах",
            "source_url": None,
            "excerpt": "См. полную correction chain.",
        }
    if evidence_id == "case:nutritionists-law":
        return {
            "catalog_id": evidence_id,
            "source": "correction_case",
            "headline": "Кейс о нутрициологах",
            "source_url": None,
            "excerpt": "См. полную приватную correction chain.",
        }
    if evidence_id.startswith("owner:"):
        return {
            "catalog_id": evidence_id,
            "source": "owner_decision",
            "headline": "Прямое редакторское решение владельца",
            "source_url": None,
            "excerpt": rule["statement"],
        }
    card = by_id[evidence_id]
    return {
        "catalog_id": evidence_id,
        "source": card["source"],
        "headline": card.get("headline"),
        "source_url": card.get("source_url"),
        "excerpt": excerpt(card.get("text_source") or card.get("text_plain") or ""),
    }


def merge_corrections(existing: list[dict], seeds: list[dict]) -> list[dict]:
    """Keep owner-recorded corrections when deterministic artifacts are rebuilt."""
    merged = {row["correction_id"]: row for row in seeds}
    for row in existing:
        merged[row["correction_id"]] = row
    return list(merged.values())


def build_fragments(exemplars: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for exemplar in exemplars:
        parts = paragraphs({"text_source": exemplar["text"]})
        for position, value in enumerate(parts):
            if not 25 <= len(value) <= 1200:
                continue
            kind = fragment_kind(value, position, len(parts))
            if kind == "explanation_or_body" and position not in {1, len(parts) // 3, len(parts) // 2, (2 * len(parts)) // 3}:
                continue
            digest = hashlib.sha256(f"{exemplar['catalog_id']}:{position}:{value}".encode("utf-8")).hexdigest()[:20]
            rows.append({
                "fragment_id": f"frag:{digest}",
                "catalog_id": exemplar["catalog_id"],
                "source": exemplar["source"],
                "source_url": exemplar.get("source_url"),
                "fragment_kind": kind,
                "text": value,
                "context_before": parts[position - 1][-350:] if position else "",
                "context_after": parts[position + 1][:350] if position + 1 < len(parts) else "",
                "dominant_job": exemplar["dominant_job"],
                "composition_recipe": exemplar["composition_recipe"],
                "surface_context": exemplar.get("surface_context"),
                "cluster_id": exemplar["catalog_id"],
                "media_dependency": exemplar["media_dependency"],
                "media_note": exemplar.get("media_note"),
                "media_hypothesis": exemplar.get("media_hypothesis"),
                "performance_signals": exemplar.get("performance_signals") or {},
                "review_status": "candidate_unreviewed",
                "reuse_instruction": "Use as a source-linked pattern; do not paste automatically.",
            })
    return rows


def build_index(
    path: Path,
    rules: list[dict],
    exemplars: list[dict],
    fragments: list[dict],
    corrections: list[dict],
    rhetoric: list[dict] | None = None,
    corpus: list[dict] | None = None,
) -> None:
    rhetoric = rhetoric or []
    corpus = corpus or []
    with closing(sqlite3.connect(path)) as db:
        db.executescript("""
            DROP TABLE IF EXISTS rules;
            DROP TABLE IF EXISTS exemplars;
            DROP TABLE IF EXISTS fragments;
            DROP TABLE IF EXISTS rhetoric;
            DROP TABLE IF EXISTS corrections;
            DROP TABLE IF EXISTS corpus;
            DROP TABLE IF EXISTS voice_fts;
            CREATE TABLE rules (rule_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
            CREATE TABLE exemplars (exemplar_id TEXT PRIMARY KEY, catalog_id TEXT NOT NULL, payload_json TEXT NOT NULL);
            CREATE TABLE fragments (fragment_id TEXT PRIMARY KEY, catalog_id TEXT NOT NULL, payload_json TEXT NOT NULL);
            CREATE TABLE rhetoric (entry_id TEXT PRIMARY KEY, catalog_id TEXT NOT NULL, payload_json TEXT NOT NULL);
            CREATE TABLE corrections (correction_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
            CREATE TABLE corpus (corpus_id TEXT PRIMARY KEY, catalog_id TEXT NOT NULL, payload_json TEXT NOT NULL);
            CREATE VIRTUAL TABLE voice_fts USING fts5(kind UNINDEXED, item_id UNINDEXED, catalog_id UNINDEXED, headline, text, tags, tokenize='unicode61 remove_diacritics 2');
        """)
        for row in rules:
            db.execute("INSERT INTO rules VALUES (?, ?)", (row["rule_id"], json.dumps(row, ensure_ascii=False)))
            db.execute("INSERT INTO voice_fts VALUES (?, ?, ?, ?, ?, ?)", ("rule", row["rule_id"], "", row["statement"], f"{row['mechanism']} {row['counter_boundary']}", " ".join([row["section"], *row["scope"]])))
        for row in exemplars:
            db.execute("INSERT INTO exemplars VALUES (?, ?, ?)", (row["exemplar_id"], row["catalog_id"], json.dumps(row, ensure_ascii=False)))
            db.execute("INSERT INTO voice_fts VALUES (?, ?, ?, ?, ?, ?)", ("exemplar", row["exemplar_id"], row["catalog_id"], row.get("headline") or "", row["text"], f"{row['dominant_job']} {row['composition_recipe']} {row['surface_context']}"))
        for row in fragments:
            db.execute("INSERT INTO fragments VALUES (?, ?, ?)", (row["fragment_id"], row["catalog_id"], json.dumps(row, ensure_ascii=False)))
            db.execute("INSERT INTO voice_fts VALUES (?, ?, ?, ?, ?, ?)", ("candidate", row["fragment_id"], row["catalog_id"], "", row["text"], f"{row['fragment_kind']} {row['dominant_job']} {row['composition_recipe']}"))
        for row in rhetoric:
            db.execute("INSERT INTO rhetoric VALUES (?, ?, ?)", (row["entry_id"], row.get("catalog_id") or "", json.dumps(row, ensure_ascii=False)))
            tags = " ".join(
                str(value)
                for value in (
                    row.get("family"), row.get("subtype"), row.get("dominant_job"),
                    row.get("surface_context"), *(row.get("topics") or []),
                    *(row.get("products") or []),
                )
                if value
            )
            db.execute(
                "INSERT INTO voice_fts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "rhetoric", row["entry_id"], row.get("catalog_id") or "",
                    row.get("function") or "", row["text"], tags,
                ),
            )
        for row in corrections:
            db.execute("INSERT INTO corrections VALUES (?, ?)", (row["correction_id"], json.dumps(row, ensure_ascii=False)))
            catalog_id = (row.get("context") or {}).get("catalog_id") or row.get("case_id") or ""
            db.execute("INSERT INTO voice_fts VALUES (?, ?, ?, ?, ?, ?)", ("correction", row["correction_id"], catalog_id, row["title"], row["full_case"], " ".join(row["candidate_rules"])))
        for row in corpus:
            db.execute("INSERT INTO corpus VALUES (?, ?, ?)", (row["corpus_id"], row["catalog_id"], json.dumps(row, ensure_ascii=False)))
            db.execute(
                "INSERT INTO voice_fts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "corpus", row["corpus_id"], row["catalog_id"],
                    row.get("headline") or "", row["text"],
                    f"{row.get('dominant_job') or ''} {row.get('surface_context') or ''}",
                ),
            )
        db.execute("INSERT INTO voice_fts(voice_fts) VALUES ('optimize')")
        db.commit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cards", type=Path, required=True)
    parser.add_argument("--assessments", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--exemplars", type=Path, required=True)
    parser.add_argument("--writer-contract", type=Path, required=True)
    parser.add_argument("--editorial-linking", type=Path, required=True)
    parser.add_argument("--case-study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    output = private(args.output)
    output.mkdir(parents=True, exist_ok=True)
    reviewed_rhetoric_path = output / "rhetorical-library-reviewed.jsonl"
    reviewed_rhetoric_path.touch(exist_ok=True)
    inputs = [
        args.cards, args.assessments, args.rules, args.exemplars,
        args.writer_contract, args.editorial_linking, args.case_study,
    ]
    inputs.append(reviewed_rhetoric_path)
    digest = combined_digest(inputs)
    materialized_at = datetime.now(timezone.utc).isoformat()
    state_path = output / "analysis-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    if (
        not args.force
        and materialization_state_is_current(state, digest)
        and artifacts_ready(
            output,
            (
                "voice-evidence.jsonl", "exemplar-bank-reviewed.jsonl",
                "rhetorical-slots-candidates.jsonl", "correction-memory.jsonl",
                "context-matrix.json", "editorial-linking-v1.md",
                "voice-passport-v1.md", "semantic-report.json",
            ),
            "voice-index.sqlite",
        )
    ):
        print(json.dumps({"status": "cache_hit", "output": str(output)}, ensure_ascii=False))
        return 0

    cards = read_jsonl(private(args.cards))
    by_id = {card["catalog_id"]: card for card in cards}
    assessments = {row["catalog_id"]: row for row in read_jsonl(private(args.assessments))}
    rules_payload = json.loads(args.rules.read_text(encoding="utf-8"))
    rules = rules_payload["rules"]
    exemplar_specs = json.loads(args.exemplars.read_text(encoding="utf-8"))["exemplars"]
    missing = sorted({spec["catalog_id"] for spec in exemplar_specs if spec["catalog_id"] not in by_id})
    missing_evidence = sorted({
        item
        for rule in rules
        for item in rule["evidence_ids"]
        if not item.startswith(("case:", "owner:")) and item not in by_id
    })
    if missing or missing_evidence:
        raise ValueError(f"missing catalog ids: exemplars={missing}; evidence={missing_evidence}")

    invalid_without_override = sorted(
        spec["catalog_id"]
        for spec in exemplar_specs
        if assessments.get(spec["catalog_id"])
        and assessments[spec["catalog_id"]].get("voice_use") != "eligible"
        and not spec.get("eligibility_override")
    )
    if invalid_without_override:
        raise ValueError(f"non-eligible exemplars require explicit override: {invalid_without_override}")

    reviewed_exemplars = []
    for spec in exemplar_specs:
        card = by_id[spec["catalog_id"]]
        assessment = assessments.get(spec["catalog_id"], {})
        reviewed_exemplars.append({
            "exemplar_id": f"ex:{spec['catalog_id']}",
            "catalog_id": spec["catalog_id"],
            "source": card["source"],
            "source_url": card.get("source_url"),
            "published_at": card.get("published_at"),
            "headline": card.get("headline"),
            "text": visible_text(card.get("text_source") or card.get("text_plain") or ""),
            "dominant_job": spec["job"],
            "composition_recipe": spec["recipe"],
            "strength": spec["strength"],
            "surface_context": assessment.get("surface_context"),
            "era": assessment.get("era"),
            "related_versions": list(dict.fromkeys([
                *(spec.get("related_versions") or []),
                *(assessment.get("related_versions") or []),
            ])),
            "exact_cluster_ids": assessment.get("exact_cluster_ids") or [],
            "media_dependency": "possible" if (card.get("media") or {}).get("presence") == "present" else "none_recorded",
            "media_note": (card.get("media") or {}).get("note"),
            "media_hypothesis": (card.get("media") or {}).get("hypothesis"),
            "performance_signals": (card.get("context") or {}).get("metrics_at_export") or {},
            "review_status": "strong_model_reviewed",
            "eligibility_override": spec.get("eligibility_override"),
        })

    evidence_rows = []
    for rule in rules:
        evidence = [evidence_item(item, rule, by_id) for item in rule["evidence_ids"]]
        evidence_rows.append({**rule, "evidence": evidence, "evidence_count": len(evidence)})

    case_markdown = args.case_study.read_text(encoding="utf-8")
    case_sections = split_case(case_markdown)
    seed_corrections = [{
        "correction_id": "correction:cutlets-v1",
        "title": "Котлеты: от буквального нейрослопа к авторской конструкции",
        "source_file": str(args.case_study),
        "request": case_sections.get("1. Задача автора"),
        "failed_attempt_and_feedback": case_sections.get("2. Первый ответ ИИ: что было не так"),
        "intermediate_attempt": case_sections.get("3. Вторая попытка ИИ: частично лучше, но всё ещё не эталон"),
        "owner_draft": case_sections.get("4. Авторский черновик: эталон направления"),
        "functional_explanation": case_sections.get("5. Что здесь работает"),
        "fact_boundary": case_sections.get("6. Фактологическая рамка для итоговой версии"),
        "candidate_rules": [
            "hook_is_conflict", "false_rule_then_reframe", "fact_serves_choice",
            "why_it_matters", "cta_continues_value", "spoken_not_casual_tokens",
            "product_preposition_in_masterclass"
        ],
        "full_case": case_markdown,
        "status": "owner_confirmed_direction",
    }]
    correction_path = output / "correction-memory.jsonl"
    corrections = merge_corrections(read_jsonl(correction_path) if correction_path.exists() else [], seed_corrections)
    reviewed_rhetoric = read_jsonl(reviewed_rhetoric_path) if reviewed_rhetoric_path.exists() else []
    for row in reviewed_rhetoric:
        if row.get("review_status") != "semantic_reviewed" or not row.get("review_provenance"):
            raise ValueError(f"invalid reviewed rhetoric entry: {row.get('entry_id')}")

    evidence_rows = stamp(evidence_rows, created_at=materialized_at, input_digest=digest)
    reviewed_exemplars = stamp(reviewed_exemplars, created_at=materialized_at, input_digest=digest)
    corrections = stamp(corrections, created_at=materialized_at, input_digest=digest)
    fragments = stamp(build_fragments(reviewed_exemplars), created_at=materialized_at, input_digest=digest)
    searchable_corpus = []
    for catalog_id, assessment in assessments.items():
        if assessment.get("voice_use") != "eligible" or catalog_id not in by_id:
            continue
        card = by_id[catalog_id]
        corpus_text = visible_text(card.get("text_source") or card.get("text_plain") or "")
        searchable_corpus.append({
            "corpus_id": f"corpus:{catalog_id}",
            "catalog_id": catalog_id,
            "source": card["source"],
            "source_url": card.get("source_url"),
            "headline": card.get("headline"),
            "text": corpus_text,
            "corpus_usability": corpus_usability(corpus_text),
            "dominant_job": assessment.get("dominant_job"),
            "surface_context": assessment.get("surface_context"),
            "related_versions": assessment.get("related_versions") or [],
            "exact_cluster_ids": assessment.get("exact_cluster_ids") or [],
            "media_dependency": "possible" if (card.get("media") or {}).get("presence") == "present" else "none_recorded",
            "media_note": (card.get("media") or {}).get("note"),
            "media_hypothesis": (card.get("media") or {}).get("hypothesis"),
            "performance_signals": (card.get("context") or {}).get("metrics_at_export") or {},
        })
    searchable_corpus = stamp(searchable_corpus, created_at=materialized_at, input_digest=digest)
    context_matrix = {
        "schema_version": "1.0",
        "core": "one_author_voice",
        "contexts": {
            "telegram_channel": {"likely": ["personal_presence", "continuity", "direct_cta", "poll_or_reaction"], "avoid": ["teaser_instead_of_value", "mandatory_sale"]},
            "bot_sequence": {"likely": ["one_funnel_job", "previous_step_context", "direct_button"], "avoid": ["repeating_whole_chain", "faceless_ui_voice"]},
            "pikabu_article": {"likely": ["standalone_value", "broad_hook", "proof", "objections", "nuance"], "avoid": ["internal_product_news_as_hook", "sale_before_value"]},
            "tilda_landing": {"likely": ["pain", "mechanism", "objections", "offer", "cta"], "avoid": ["stale_product_fact_as_canon"]},
            "telegraph_article_or_draft": {"likely": ["longform_source_after_dedup"], "avoid": ["automatic_published_exemplar_status"]}
        }
    }

    write_jsonl(output / "voice-evidence.jsonl", evidence_rows)
    write_jsonl(output / "exemplar-bank-reviewed.jsonl", reviewed_exemplars)
    write_jsonl(output / "rhetorical-slots-candidates.jsonl", fragments)
    write_jsonl(reviewed_rhetoric_path, reviewed_rhetoric)
    write_jsonl(correction_path, corrections)
    (output / "context-matrix.json").write_text(json.dumps(context_matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    editorial_linking = args.editorial_linking.read_text(encoding="utf-8").rstrip()
    (output / "editorial-linking-v1.md").write_text(editorial_linking + "\n", encoding="utf-8")
    passport_lines = [
        args.writer_contract.read_text(encoding="utf-8").rstrip(),
        "\n\n# Приложение: редакционные ссылки и паутина контента\n\n",
        editorial_linking,
        "\n\n# Приложение: карта доказательств\n",
        "Полные цитаты и тексты хранятся только в приватном корпусе. Ниже — источники правил.\n",
    ]
    for row in evidence_rows:
        passport_lines.append(f"\n## {row['rule_id']}\n\n{row['statement']}\n")
        for item in row["evidence"]:
            link = f" — {item['source_url']}" if item.get("source_url") else ""
            passport_lines.append(f"- `{item['catalog_id']}`: {item.get('headline') or item['source']}{link}\n")
    (output / "voice-passport-v1.md").write_text("".join(passport_lines), encoding="utf-8")
    build_index(
        output / "voice-index.sqlite", evidence_rows, reviewed_exemplars,
        fragments, corrections, reviewed_rhetoric, searchable_corpus,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "materialization_version": MATERIALIZATION_VERSION,
        "materialized_at": materialized_at,
        "input_digest": digest,
        "rules": len(evidence_rows),
        "rules_by_section": dict(Counter(row["section"] for row in evidence_rows)),
        "reviewed_exemplars": len(reviewed_exemplars),
        "exemplars_by_source": dict(Counter(row["source"] for row in reviewed_exemplars)),
        "exemplars_by_job": dict(Counter(row["dominant_job"] for row in reviewed_exemplars)),
        "rhetorical_candidates_from_reviewed_exemplars": len(fragments),
        "candidate_fragments_by_kind": dict(Counter(row["fragment_kind"] for row in fragments)),
        "semantic_reviewed_rhetoric": len(reviewed_rhetoric),
        "searchable_corpus": len(searchable_corpus),
        "correction_chains": len(corrections),
    }
    (output / "semantic-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    state.update({
        "materialization_sha256": digest,
        "materialization_version": MATERIALIZATION_VERSION,
        "materialized_at": materialized_at,
        "checkpoint": "semantic_materialization_complete",
        "strong_model_review": "completed_seed",
        "user_calibration": "pending",
    })
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "materialized", "output": str(output), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
