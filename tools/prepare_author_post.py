"""Build a compact private retrieval pack and fact contract for one writing task."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from search_author_voice import private, search_index


SCHEMA_VERSION = "1.0"
PACK_VERSION = "author-post-pack-v5-20260826"
EDIT_MODES = {
    "draft",
    "targeted_edit",
    "proofread",
    "structure_only",
    "text_only",
    "rewrite",
    "creative_rebuild",
}
MODES_WITHOUT_VOICE_RETRIEVAL = {"proofread", "structure_only"}
ARTICLE_FORMAT_CONTEXTS = {
    "article", "site_article", "course_material", "masterclass_material", "intensive_article"
}
COURSE_PACKAGE_CONTEXTS = {"course", "course_package", "masterclass_course"}
RETRIEVAL_PROFILES = {
    # Counts are ceilings, not quotas. Character budgets keep long exemplars from
    # turning a routine request into an unbounded context load.
    "light": {
        "exemplars": 2, "rhetoric": 4, "corrections": 0, "rules": 3,
        "history": 4, "full_text_characters": 16_000,
    },
    "standard": {
        "exemplars": 5, "rhetoric": 8, "corrections": 1, "rules": 6,
        "history": 8, "full_text_characters": 36_000,
    },
    "deep": {
        "exemplars": 7, "rhetoric": 12, "corrections": 2, "rules": 8,
        "history": 12, "full_text_characters": 80_000,
    },
}


def distinct_version_groups(rows: list[dict], limit: int, blocked: set[str] | None = None) -> list[dict]:
    """Keep one retrieval slot per exact/related version family."""
    seen = set(blocked or set())
    selected: list[dict] = []
    for row in rows:
        group = {
            value
            for value in [
                row.get("catalog_id"),
                *(row.get("related_versions") or []),
                *(row.get("exact_cluster_ids") or []),
            ]
            if value
        }
        if seen.intersection(group):
            continue
        selected.append(row)
        seen.update(group)
        if len(selected) >= limit:
            break
    return selected


def bounded_full_text(rows: list[dict], keys: tuple[str, ...], character_budget: int) -> list[dict]:
    """Keep ranked rows inside a hard context ceiling, truncating only the top row if needed."""
    selected: list[dict] = []
    used = 0
    for row in rows:
        size = sum(len(str(row.get(key) or "")) for key in keys)
        if used + size <= character_budget:
            selected.append(row)
            used += size
            continue
        if selected:
            continue
        bounded = dict(row)
        primary_key = next((key for key in keys if bounded.get(key)), None)
        if primary_key:
            text = str(bounded[primary_key])
            marker = "\n\n[ФРАГМЕНТ СОКРАЩЁН ЛИМИТОМ КОНТЕКСТА]\n\n"
            available = max(0, character_budget - len(marker))
            head = available * 2 // 3
            tail = available - head
            bounded[primary_key] = (
                text[:head]
                + marker
                + (text[-tail:] if tail else "")
            )
            bounded["context_truncated"] = True
        selected.append(bounded)
        break
    return selected


def build_pack(task_path: Path, index_path: Path) -> dict:
    task_path, index_path = private(task_path), private(index_path)
    task = json.loads(task_path.read_text(encoding="utf-8"))
    note = str(task.get("note") or "").strip()
    if not note:
        raise ValueError("task.note is required")
    query = str(task.get("search_query") or note)
    job = task.get("job")
    preferred_surface = task.get("surface_context")
    edit_mode = task.get("edit_mode") or "draft"
    if edit_mode not in EDIT_MODES:
        raise ValueError(f"unknown edit_mode: {edit_mode}")
    source_text = task.get("source_text")
    if edit_mode in {"targeted_edit", "proofread", "structure_only", "text_only", "rewrite"} and not isinstance(source_text, str):
        raise ValueError(f"task.source_text is required for {edit_mode}")
    editable_scope = task.get("editable_scope")
    if edit_mode == "targeted_edit":
        if not isinstance(editable_scope, list) or not editable_scope:
            raise ValueError("task.editable_scope is required for targeted_edit")
        editable_fragments = [
            item if isinstance(item, str) else item.get("source")
            for item in editable_scope
        ]
        if any(not isinstance(item, str) or not item for item in editable_fragments):
            raise ValueError("each targeted_edit scope item must contain a source fragment")
        if any(source_text.count(item) != 1 for item in editable_fragments):
            raise ValueError("each targeted_edit source fragment must occur exactly once")
    rewrite_goal = task.get("rewrite_goal")
    if edit_mode == "rewrite" and not str(rewrite_goal or "").strip():
        raise ValueError("task.rewrite_goal is required for rewrite")
    format_profile = task.get("format_profile")
    if not format_profile:
        if preferred_surface in COURSE_PACKAGE_CONTEXTS:
            format_profile = "course"
        elif preferred_surface in ARTICLE_FORMAT_CONTEXTS:
            format_profile = "article"
    effective_product = task.get("product") or (
        "masterclass" if preferred_surface == "masterclass_course" else None
    )
    course_outline = task.get("course_outline")
    if format_profile == "course" and not course_outline:
        raise ValueError("task.course_outline is required for a full course")
    if format_profile == "course" and (
        not isinstance(course_outline, list)
        or any(
            not isinstance(day, dict)
            or day.get("day") is None
            or not isinstance(day.get("materials"), list)
            or not day["materials"]
            or any(not isinstance(material, str) or not material.strip() for material in day["materials"])
            for day in course_outline
        )
    ):
        raise ValueError("task.course_outline must contain days with non-empty material names")
    if format_profile == "course" and not effective_product:
        raise ValueError("task.product is required for a non-Masterclass full course")
    retrieval_depth = task.get("retrieval_depth") or "standard"
    if retrieval_depth not in RETRIEVAL_PROFILES:
        raise ValueError(f"unknown retrieval_depth: {retrieval_depth}")
    retrieval_profile = RETRIEVAL_PROFILES[retrieval_depth]
    rhetorical_queries = task.get("rhetorical_queries") or [{"query": query}]
    retrieval = {
        "exemplars": [],
        "rhetoric": [],
        "corrections": [],
        "rules": [],
        "topic_history": [],
    }
    if edit_mode not in MODES_WITHOUT_VOICE_RETRIEVAL:
        rhetoric_results: list[dict] = []
        seen_rhetoric: set[str] = set()
        for specification in rhetorical_queries:
            phrase = str(specification.get("query") or "").strip()
            if not phrase:
                continue
            found = search_index(
                index_path,
                phrase,
                kind_filter="rhetoric",
                job=specification.get("job") or job,
                family=specification.get("family"),
                preferred_surface=preferred_surface,
                limit=int(specification.get("limit") or retrieval_profile["rhetoric"]),
            )["results"]
            for row in found:
                if row["item_id"] not in seen_rhetoric:
                    rhetoric_results.append(row)
                    seen_rhetoric.add(row["item_id"])
        exemplar_candidates = search_index(
            index_path, query, kind_filter="exemplar", job=job,
            preferred_surface=preferred_surface,
            limit=max(10, retrieval_profile["exemplars"] * 5),
            include_full_text=True,
        )["results"]
        exemplars = bounded_full_text(
            distinct_version_groups(exemplar_candidates, retrieval_profile["exemplars"]),
            ("full_text",),
            retrieval_profile["full_text_characters"],
        )
        blocked_versions = {
            value
            for row in exemplars
            for value in [row.get("catalog_id"), *(row.get("related_versions") or []), *(row.get("exact_cluster_ids") or [])]
            if value
        }
        history_candidates = search_index(
            index_path, query, kind_filter="corpus", job=job,
            preferred_surface=preferred_surface,
            exclude_technical=True,
            limit=max(10, retrieval_profile["history"] * 4),
        )["results"]
        corrections = search_index(
            index_path, query, kind_filter="correction",
            limit=retrieval_profile["corrections"],
            include_full_text=True,
        )["results"] if retrieval_profile["corrections"] else []
        remaining_full_text_budget = max(
            0,
            retrieval_profile["full_text_characters"]
            - sum(len(str(row.get("full_text") or "")) for row in exemplars),
        )
        retrieval = {
            "exemplars": exemplars,
            "rhetoric": rhetoric_results[:retrieval_profile["rhetoric"]],
            "corrections": bounded_full_text(
                corrections, ("full_case",), remaining_full_text_budget
            ) if remaining_full_text_budget else [],
            "rules": search_index(
                index_path, query, kind_filter="rule", limit=retrieval_profile["rules"]
            )["results"],
            "topic_history": distinct_version_groups(
                history_candidates, retrieval_profile["history"], blocked_versions
            ),
        }
        if task.get("include_unreviewed_candidates"):
            retrieval["unreviewed_candidates"] = search_index(
                index_path, query, kind_filter="candidate", job=job, limit=8
            )["results"]
    runtime_sources = {
        "authoring_skill": "content/author-voice/skill/edabalans-writer/SKILL.md",
        "editing_modes": "content/author-voice/editing-modes-v1.md",
    }
    if edit_mode not in MODES_WITHOUT_VOICE_RETRIEVAL:
        runtime_sources["writer_contract"] = "content/author-voice/writer-contract-v1.md"
    if effective_product or task.get("cta") or job == "sales":
        runtime_sources["product_fact_router"] = "content/author-voice/product-fact-router.md"
    if (
        task.get("cta")
        or task.get("linking_context")
        or task.get("comment_prompt")
        or task.get("series_context")
        or task.get("chain_context")
        or job == "sales"
        or preferred_surface == "bot_sequence"
    ):
        runtime_sources["editorial_linking"] = "content/author-voice/editorial-linking-v1.md"
    if format_profile in {"article", "course"}:
        runtime_sources["article_standard"] = "docs/knowledge-base/ARTICLE_STANDARD.md"
    if format_profile == "course":
        course_structure_source = task.get("course_structure_source")
        if not course_structure_source and preferred_surface == "masterclass_course":
            course_structure_source = "docs/knowledge-base/modules/masterclass/COURSE_STRUCTURE_CONTRACT.md"
        if not course_structure_source:
            raise ValueError("task.course_structure_source is required for a non-Masterclass full course")
        runtime_sources["course_structure"] = str(course_structure_source)
    if task.get("include_course_visual"):
        runtime_sources["course_visual"] = str(
            task.get("course_visual_source")
            or "docs/knowledge-base/modules/masterclass/COURSE_VISUAL_SYSTEM.md"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "pack_version": PACK_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content_contract": {
            "note": note,
            "goal": task.get("goal"),
            "audience": task.get("audience"),
            "surface_context": task.get("surface_context"),
            "format_profile": format_profile,
            "course_outline": course_outline,
            "chain_context": task.get("chain_context"),
            "dominant_job": job,
            "required_facts": task.get("required_facts") or [],
            "forbidden_claims": task.get("forbidden_claims") or [],
            "product": effective_product,
            "cta": task.get("cta"),
            "media_context": task.get("media_context") or [],
            "unknowns": task.get("unknowns") or [],
            "target_emotion": task.get("target_emotion"),
            "reader_starting_belief": task.get("reader_starting_belief"),
            "central_conflict": task.get("central_conflict"),
            "stakes": task.get("stakes"),
            "argument_route": task.get("argument_route") or [],
            "author_role_and_turn": task.get("author_role_and_turn"),
            "fact_placement": task.get("fact_placement") or [],
            "product_bridge_reason": task.get("product_bridge_reason"),
            "desired_action": task.get("desired_action"),
            "edit_mode": edit_mode,
            "source_text": source_text,
            "protected_text": task.get("protected_text"),
            "editable_scope": editable_scope,
            "rewrite_goal": rewrite_goal,
            "rewrite_preserve": task.get("rewrite_preserve") or [
                "central thesis",
                "required facts",
                "author position",
                "useful examples",
                "links and media unless explicitly allowed",
            ],
            "comparison_texts": task.get("comparison_texts") or [],
            "allow_link_media_changes": bool(task.get("allow_link_media_changes")),
            "rhetorical_queries": rhetorical_queries,
            "retrieval_depth": retrieval_depth,
        },
        "retrieval": retrieval,
        "runtime_sources": runtime_sources,
        "instructions": [
            (
                "Return the requested complete course package from course_outline, preserving its days and material boundaries."
                if format_profile == "course"
                else "Write one ready text, not a menu of blocks."
            ),
            "Facts come only from the content contract and current product canon.",
            "Use retrieved material as source-linked patterns; do not paste it automatically.",
            "Build the emotion and argument route before drafting sentences.",
            "Apply editing permissions from editing-modes-v1.md without widening them.",
            "For a site article or course material, apply ARTICLE_STANDARD.md; never invent headings only to create a table of contents.",
            "Apply the review policy owned by the selected normative contract.",
        ],
        "review_policy": {
            "policy_id": (
                "protected-edit-v1"
                if edit_mode in MODES_WITHOUT_VOICE_RETRIEVAL
                else "writer-three-layer-v1"
            ),
            "source": (
                "content/author-voice/editing-modes-v1.md"
                if edit_mode in MODES_WITHOUT_VOICE_RETRIEVAL
                else "content/author-voice/writer-contract-v1.md#проход-3-три-слоя-проверки"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True, help="Private JSON writing task")
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Private retrieval-pack JSON")
    args = parser.parse_args()
    output = private(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pack = build_pack(args.task, args.index)
    output.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "prepared", "output": str(output), "counts": {key: len(value) for key, value in pack["retrieval"].items()}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
