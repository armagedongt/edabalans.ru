"""Build and validate the private source-linked rhetorical library.

Candidate extraction is deterministic and cheap. It never promotes a fragment to
semantic_reviewed; reviewed batches must carry explicit provenance and are merged
separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from build_author_voice import paragraphs, private, visible_text


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCHEMA_VERSION = "1.0"
TAXONOMY_VERSION = "rhetorical-taxonomy-v1-20260826"
REVIEW_PROMPT_VERSION = "rhetorical-review-v1"
ALLOWED_VOICE_USE = {"eligible", "fragment_only"}
ALLOWED_AUTHORSHIP = {"own_published", "own_draft", "own_reply", "owner_approved_edit"}
FAMILIES = {
    "hook", "pain_and_importance", "causal_chain", "reframe_and_turn",
    "explanation_and_proof", "humor_and_sharpness", "authority",
    "practical_landing", "product_bridge", "cta", "comment_prompt", "ending",
    "formatting_and_punctuation",
}
FAMILY_HINTS = {
    "pain_and_importance": re.compile(r"\b(голод|срыв|надоел|устал|страш|стыд|вина|не получ|заброс|верн[её]тся|по кругу)\w*", re.I),
    "causal_chain": re.compile(r"(?:→|из-за|потому что|сначала|потом|снова|в итоге|по кругу)", re.I),
    "reframe_and_turn": re.compile(r"\b(только вот|на самом деле|дело не в|проблема начинается|так,? стоп|есть нюанс|а что я|вот и получается)\b", re.I),
    "explanation_and_proof": re.compile(r"\b(исследован|по данным|потому что|механизм|ккал|белк|жир|дневник|за \d+|\d+\s*(?:%|г|кг|лет|час))\w*", re.I),
    "humor_and_sharpness": re.compile(r"\b(хз|ну ал[её]|успех|хрен|хуй|пиздец|блять|ч[её]рт|кукух|епона|ясен пень)\w*|[😂🤣😅¯]", re.I),
    "authority": re.compile(r"\b(я (?:работ|виж|зна|уме|ни разу)|мой подход|моя задача|сотн\w*|за \d+ (?:года|лет))", re.I),
    "practical_landing": re.compile(r"\b(что делать|как выбрать|попробуйте|сделайте|начните|добавьте|уберите|критерий|действи|шаг)\w*", re.I),
    "product_bridge": re.compile(r"\b(в мастер-?классе|в интенсиве|на курсе|в программе|в сопровождении)\b", re.I),
    "cta": re.compile(r"\b(жмите|переходите|читайте|пишите|забирайте|выбирайте|купить|записаться|худеть)\b|https?://|telegram\.me/", re.I),
    "comment_prompt": re.compile(r"\b(напишите в коммент|расскажите в коммент|что думаете|как вам|а у вас|кто из вас)\w*", re.I),
}
REQUIRED_REVIEW_FIELDS = {
    "entry_id", "text", "catalog_id", "family", "subtype", "function",
    "mechanism", "works_when", "avoid_when", "reuse_instruction",
    "review_status", "review_provenance",
}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def text_hash(value: str) -> str:
    normalized = re.sub(r"\W+", " ", value.casefold(), flags=re.UNICODE).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def family_hints(value: str, position: int, total: int) -> list[str]:
    hints = [family for family, pattern in FAMILY_HINTS.items() if pattern.search(value)]
    if position == 0:
        hints.insert(0, "hook")
    if position >= total - 2:
        hints.append("ending")
    if re.search(r"[!?…]|\*\*|__|[A-ZА-ЯЁ]{3,}", value):
        hints.append("formatting_and_punctuation")
    return list(dict.fromkeys(hints))


def candidate_priority(assessment: dict, hints: list[str], value: str) -> int:
    score = int(assessment.get("quality_score") or 0)
    score += min(6, len(hints) * 2)
    score += 2 if 60 <= len(value) <= 650 else 0
    score += 2 if assessment.get("era") == "current_2025_plus" else 0
    score += 1 if assessment.get("voice_use") == "fragment_only" else 0
    return score


def build_candidates(cards: list[dict], assessments: list[dict]) -> list[dict]:
    by_id = {row["catalog_id"]: row for row in assessments}
    rows: list[dict] = []
    for card in cards:
        assessment = by_id.get(card.get("catalog_id"))
        if not assessment or assessment.get("voice_use") not in ALLOWED_VOICE_USE:
            continue
        if assessment.get("authorship") not in ALLOWED_AUTHORSHIP:
            continue
        text = visible_text(card.get("text_source") or card.get("text_plain") or "")
        parts = paragraphs({"text_source": text})
        for position, value in enumerate(parts):
            value = value.strip()
            if not 20 <= len(value) <= 1400:
                continue
            hints = family_hints(value, position, len(parts))
            if not hints and position not in {1, len(parts) // 2}:
                continue
            digest = text_hash(value)
            candidate_id = "cand:" + hashlib.sha256(
                f"{card['catalog_id']}:{position}:{digest}".encode("utf-8")
            ).hexdigest()[:20]
            media = card.get("media") or {}
            rows.append({
                "schema_version": SCHEMA_VERSION,
                "taxonomy_version": TAXONOMY_VERSION,
                "candidate_id": candidate_id,
                "text": value,
                "text_hash": digest,
                "context_before": parts[position - 1][-500:] if position else "",
                "context_after": parts[position + 1][:500] if position + 1 < len(parts) else "",
                "paragraph_position": position,
                "paragraph_count": len(parts),
                "catalog_id": card["catalog_id"],
                "source": card.get("source"),
                "source_url": card.get("source_url"),
                "cluster_id": (assessment.get("exact_cluster_ids") or [card["catalog_id"]])[0],
                "related_versions": assessment.get("related_versions") or [],
                "family_hints_auto": hints,
                "dominant_job": assessment.get("dominant_job"),
                "composition_map": assessment.get("composition_map") or [],
                "surface_context": assessment.get("surface_context"),
                "era": assessment.get("era"),
                "tone_dials": assessment.get("tone_dials") or {},
                "authorship": assessment.get("authorship"),
                "media_dependency": "possible" if media.get("presence") == "present" else assessment.get("media_status"),
                "media_note": media.get("note"),
                "media_hypothesis": media.get("hypothesis"),
                "performance_signals": (card.get("context") or {}).get("metrics_at_export") or {},
                "candidate_priority": candidate_priority(assessment, hints, value),
                "review_status": "candidate_unreviewed",
                "review_cache_key": hashlib.sha256(
                    f"{digest}:{TAXONOMY_VERSION}:{REVIEW_PROMPT_VERSION}".encode("utf-8")
                ).hexdigest(),
            })

    duplicate_groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        duplicate_groups[row["text_hash"]].append(row)
    for group in duplicate_groups.values():
        group.sort(key=lambda item: (-item["candidate_priority"], item["candidate_id"]))
        representative = group[0]["candidate_id"]
        for row in group:
            row["exact_fragment_cluster"] = representative
            row["is_exact_fragment_duplicate"] = row["candidate_id"] != representative
    return sorted(rows, key=lambda item: (-item["candidate_priority"], item["candidate_id"]))


def candidate_report(rows: list[dict]) -> dict:
    unique = [row for row in rows if not row["is_exact_fragment_duplicate"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": len(rows),
        "unique_candidates": len(unique),
        "exact_fragment_duplicates": len(rows) - len(unique),
        "by_source": dict(Counter(row["source"] for row in unique)),
        "by_job": dict(Counter(row["dominant_job"] for row in unique)),
        "family_hints": dict(Counter(hint for row in unique for hint in row["family_hints_auto"])),
        "review_status": "candidate_unreviewed",
    }


def validate_reviewed_entry(row: dict) -> None:
    missing = sorted(REQUIRED_REVIEW_FIELDS - row.keys())
    if missing:
        raise ValueError(f"reviewed entry is missing fields: {', '.join(missing)}")
    if row["family"] not in FAMILIES:
        raise ValueError(f"unknown rhetorical family: {row['family']}")
    if row["review_status"] != "semantic_reviewed":
        raise ValueError("reviewed library accepts only review_status=semantic_reviewed")
    provenance = row["review_provenance"]
    for field in ("review_prompt_version", "reviewed_at", "text_hash"):
        if not str(provenance.get(field) or "").strip():
            raise ValueError(f"review provenance is missing {field}")
    if provenance["text_hash"] != text_hash(row["text"]):
        raise ValueError(f"text hash mismatch for {row['entry_id']}")


def merge_review_batch(batch: list[dict], existing: list[dict]) -> list[dict]:
    merged = {row["entry_id"]: row for row in existing}
    for row in batch:
        validate_reviewed_entry(row)
        merged[row["entry_id"]] = row
    return sorted(merged.values(), key=lambda item: item["entry_id"])


def promote_review_decisions(
    candidates: list[dict],
    decisions: list[dict],
    existing: list[dict],
    ledger: list[dict],
    *,
    reviewed_at: str,
) -> tuple[list[dict], list[dict]]:
    by_candidate = {row["candidate_id"]: row for row in candidates}
    accepted: list[dict] = []
    ledger_by_id = {row["candidate_id"]: row for row in ledger}
    for decision in decisions:
        candidate_id = decision["candidate_id"]
        candidate = by_candidate.get(candidate_id)
        if not candidate:
            raise ValueError(f"unknown candidate id: {candidate_id}")
        outcome = decision.get("decision")
        if outcome not in {"accept", "reject"}:
            raise ValueError(f"unknown review decision for {candidate_id}: {outcome}")
        ledger_by_id[candidate_id] = {
            "candidate_id": candidate_id,
            "decision": outcome,
            "family": decision.get("family"),
            "reason": decision.get("reason"),
            "text_hash": candidate["text_hash"],
            "review_prompt_version": REVIEW_PROMPT_VERSION,
            "reviewed_at": reviewed_at,
        }
        if outcome == "reject":
            continue
        entry = {
            **{key: candidate.get(key) for key in (
                "text", "context_before", "context_after", "catalog_id", "source",
                "source_url", "cluster_id", "related_versions", "dominant_job",
                "composition_map", "surface_context", "era", "tone_dials",
                "authorship", "media_dependency", "media_note", "media_hypothesis",
                "performance_signals",
            )},
            "schema_version": SCHEMA_VERSION,
            "taxonomy_version": TAXONOMY_VERSION,
            "entry_id": decision.get("entry_id") or candidate_id.replace("cand:", "rhet:"),
            "family": decision["family"],
            "subtype": decision["subtype"],
            "function": decision["function"],
            "mechanism": decision["mechanism"],
            "works_when": decision.get("works_when") or [],
            "avoid_when": decision.get("avoid_when") or [],
            "reuse_instruction": decision["reuse_instruction"],
            "emotion_before": decision.get("emotion_before"),
            "emotion_after": decision.get("emotion_after"),
            "topics": decision.get("topics") or [],
            "products": decision.get("products") or [],
            "audience_state": decision.get("audience_state") or [],
            "quality": decision.get("quality") or "medium",
            "confidence": decision.get("confidence") or "medium",
            "novelty": decision.get("novelty") or "known_mechanic",
            "owner_approved": bool(decision.get("owner_approved")),
            "review_status": "semantic_reviewed",
            "review_provenance": {
                "candidate_id": candidate_id,
                "review_prompt_version": REVIEW_PROMPT_VERSION,
                "reviewed_at": reviewed_at,
                "text_hash": candidate["text_hash"],
            },
        }
        validate_reviewed_entry(entry)
        accepted.append(entry)
    return merge_review_batch(accepted, existing), sorted(ledger_by_id.values(), key=lambda row: row["candidate_id"])


def select_review_batch(
    candidates: list[dict],
    reviewed: list[dict],
    *,
    family: str,
    limit: int,
    sources: set[str] | None = None,
    ledger: list[dict] | None = None,
) -> list[dict]:
    if family not in FAMILIES:
        raise ValueError(f"unknown rhetorical family: {family}")
    reviewed_candidate_ids = {
        row.get("review_provenance", {}).get("candidate_id")
        for row in reviewed
    }
    reviewed_candidate_ids.update(row.get("candidate_id") for row in (ledger or []))
    pool = [
        row for row in candidates
        if family in row.get("family_hints_auto", [])
        and not row.get("is_exact_fragment_duplicate")
        and row["candidate_id"] not in reviewed_candidate_ids
        and (not sources or row.get("source") in sources)
    ]
    pool.sort(key=lambda row: (-row["candidate_priority"], row["candidate_id"]))
    by_stratum: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in pool:
        by_stratum[(row.get("source") or "unknown", row.get("dominant_job") or "unknown")].append(row)
    chosen: list[dict] = []
    strata = sorted(by_stratum)
    while strata and len(chosen) < limit:
        remaining: list[tuple[str, str]] = []
        for stratum in strata:
            bucket = by_stratum[stratum]
            if bucket and len(chosen) < limit:
                chosen.append(bucket.pop(0))
            if bucket:
                remaining.append(stratum)
        strata = remaining
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    candidates_parser = subparsers.add_parser("candidates")
    candidates_parser.add_argument("--cards", type=Path, required=True)
    candidates_parser.add_argument("--assessments", type=Path, required=True)
    candidates_parser.add_argument("--output", type=Path, required=True)
    candidates_parser.add_argument("--report", type=Path, required=True)

    merge_parser = subparsers.add_parser("merge-review")
    merge_parser.add_argument("--batch", type=Path, required=True)
    merge_parser.add_argument("--library", type=Path, required=True)

    select_parser = subparsers.add_parser("select-batch")
    select_parser.add_argument("--candidates", type=Path, required=True)
    select_parser.add_argument("--library", type=Path, required=True)
    select_parser.add_argument("--output", type=Path, required=True)
    select_parser.add_argument("--family", choices=sorted(FAMILIES), required=True)
    select_parser.add_argument("--limit", type=int, default=40)
    select_parser.add_argument("--sources", nargs="*")
    select_parser.add_argument("--ledger", type=Path)

    promote_parser = subparsers.add_parser("promote-review")
    promote_parser.add_argument("--candidates", type=Path, required=True)
    promote_parser.add_argument("--decisions", type=Path, required=True)
    promote_parser.add_argument("--library", type=Path, required=True)
    promote_parser.add_argument("--ledger", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "candidates":
        output = private(args.output)
        report_path = private(args.report)
        rows = build_candidates(read_jsonl(private(args.cards)), read_jsonl(private(args.assessments)))
        write_jsonl(output, rows)
        report = candidate_report(rows)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "candidates_built", "output": str(output), **report}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "select-batch":
        output = private(args.output)
        chosen = select_review_batch(
            read_jsonl(private(args.candidates)),
            read_jsonl(private(args.library)),
            family=args.family,
            limit=args.limit,
            sources=set(args.sources or []) or None,
            ledger=read_jsonl(private(args.ledger)) if args.ledger else [],
        )
        write_jsonl(output, chosen)
        print(json.dumps({
            "status": "review_batch_selected",
            "family": args.family,
            "items": len(chosen),
            "by_source": dict(Counter(row["source"] for row in chosen)),
            "by_job": dict(Counter(row["dominant_job"] for row in chosen)),
            "output": str(output),
        }, ensure_ascii=False, indent=2))
        return 0

    if args.command == "promote-review":
        library_path = private(args.library)
        ledger_path = private(args.ledger)
        decisions_payload = json.loads(args.decisions.read_text(encoding="utf-8"))
        library, ledger = promote_review_decisions(
            read_jsonl(private(args.candidates)),
            decisions_payload["decisions"],
            read_jsonl(library_path),
            read_jsonl(ledger_path),
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
        write_jsonl(library_path, library)
        write_jsonl(ledger_path, ledger)
        print(json.dumps({
            "status": "review_promoted",
            "library": str(library_path),
            "semantic_reviewed": len(library),
            "ledger_entries": len(ledger),
        }, ensure_ascii=False, indent=2))
        return 0

    batch_path = private(args.batch)
    library_path = private(args.library)
    merged = merge_review_batch(read_jsonl(batch_path), read_jsonl(library_path))
    write_jsonl(library_path, merged)
    print(json.dumps({"status": "review_merged", "library": str(library_path), "entries": len(merged)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
