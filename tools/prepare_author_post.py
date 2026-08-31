"""Build a compact private retrieval pack and fact contract for one writing task."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from search_author_voice import private, search_index


SCHEMA_VERSION = "2.1"
PACK_VERSION = "author-post-pack-v8-20260831"
FACT_CHECK_PROFILES = {"instructional_strict", "editorial_materiality"}
SOURCE_BASES = {"full_source", "sparse_basis"}
AUTHOR_REUSE_MODES = {"authored_blocks_first", "original_composition"}
BLOCK_ACTIONS = {
    "verbatim",
    "light_edit",
    "expand_thesis",
    "find_author_material",
    "research_and_write",
    "write_new",
    "remove",
}
TRANSCRIPT_ROLES = {"article_source", "video_script", "context_only"}
EDIT_MODES = {
    "draft",
    "targeted_edit",
    "proofread",
    "structure_only",
    "text_only",
    "rewrite",
    "creative_rebuild",
}
MODES_WITHOUT_VOICE_RETRIEVAL = {
    "proofread", "structure_only", "targeted_edit", "text_only"
}
WORK_PROFILES = {
    "structure": {
        "edit_modes": {"structure_only"},
        "min_token_coverage": 1.0,
        "min_length_ratio": 1.0,
        "floors": (1.0, 1.0),
    },
    "transcript_to_article": {
        "edit_modes": {"rewrite"},
        "min_token_coverage": 0.60,
        "min_length_ratio": 0.55,
        "floors": (0.40, 0.35),
    },
    "new_material": {
        "edit_modes": {"draft", "creative_rebuild"},
        "min_token_coverage": 0.0,
        "min_length_ratio": 0.0,
        "floors": (0.0, 0.0),
    },
    "develop_existing": {
        "edit_modes": {"rewrite", "targeted_edit", "proofread", "text_only"},
        "min_token_coverage": 0.50,
        "min_length_ratio": 0.40,
        "floors": (0.30, 0.25),
    },
}
LEGACY_PROFILE_BY_MODE = {
    "structure_only": "structure",
    "draft": "new_material",
    "creative_rebuild": "new_material",
    "rewrite": "develop_existing",
    "targeted_edit": "develop_existing",
    "proofread": "develop_existing",
    "text_only": "develop_existing",
}
ARTICLE_FORMAT_CONTEXTS = {
    "article", "site_article", "course_material", "masterclass_material", "intensive_article"
}
COURSE_MATERIAL_CONTEXTS = {"course_material", "masterclass_material", "intensive_article"}
COURSE_PACKAGE_CONTEXTS = {"course", "course_package", "masterclass_course"}
ORIGINAL_COMPOSITION_CONTEXTS = {"telegram", "telegram_channel"}
STRICT_FACT_SURFACES = {
    "course",
    "course_material",
    "course_package",
    "intensive_article",
    "masterclass_course",
    "masterclass_material",
}
EDITORIAL_FACT_SURFACES = {
    "article",
    "bot_sequence",
    "landing",
    "pikabu",
    "pikabu_article",
    "service_text",
    "site_article",
    "telegram",
    "telegram_channel",
}
KNOWN_FACT_SURFACES = STRICT_FACT_SURFACES | EDITORIAL_FACT_SURFACES
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


def bounded_complete_full_text(
    rows: list[dict], key: str, character_budget: int
) -> list[dict]:
    """Keep only complete source texts; omitted rows can be fetched on demand."""
    selected: list[dict] = []
    used = 0
    for row in rows:
        size = len(str(row.get(key) or ""))
        if not size or used + size > character_budget:
            continue
        selected.append(row)
        used += size
    return selected


def authored_reuse_retrieval(
    index_path: Path,
    block_outline: list[str],
    *,
    preferred_surface: str | None,
    character_budget: int,
    candidates_per_block: int,
) -> dict:
    """Retrieve reusable authored sources separately for every planned block."""
    rows_by_block: list[list[dict]] = []
    blocks: list[dict] = []
    for block in block_outline:
        found = search_index(
            index_path,
            block,
            kind_filter="corpus",
            preferred_surface=preferred_surface,
            exclude_technical=True,
            limit=max(4, candidates_per_block * 2),
            include_full_text=True,
        )["results"]
        candidates = distinct_version_groups(found, candidates_per_block)
        rows_by_block.append(candidates)
        blocks.append({
            "block": block,
            "search_status": "candidates_found" if candidates else "uncovered",
            "candidates": [
                {
                    key: value
                    for key, value in row.items()
                    if key != "full_text"
                }
                for row in candidates
            ],
        })

    # Round-robin keeps the first block from consuming the full-text budget.
    ordered_sources: list[dict] = []
    seen: set[str] = set()
    max_rank = max((len(rows) for rows in rows_by_block), default=0)
    for rank in range(max_rank):
        for rows in rows_by_block:
            if rank >= len(rows):
                continue
            row = rows[rank]
            identity = str(row.get("item_id") or row.get("catalog_id") or "")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            ordered_sources.append(row)
    sources = bounded_complete_full_text(
        ordered_sources,
        "full_text",
        character_budget,
    )
    included = {str(row.get("item_id") or "") for row in sources}
    for block in blocks:
        for candidate in block["candidates"]:
            candidate["full_text_in_pack"] = str(candidate.get("item_id") or "") in included
    return {
        "blocks": blocks,
        "sources": sources,
        "fetch_missing_full_text": {
            "tool": "tools/search_author_voice.py",
            "index": str(index_path),
            "arguments": ["--item-id", "<item_id>", "--include-full-text"],
        },
    }


def fact_check_profile(
    task: dict,
    preferred_surface: str | None,
    format_profile: str | None,
) -> str:
    requested = task.get("fact_check_profile")
    if requested is not None:
        if requested not in FACT_CHECK_PROFILES:
            raise ValueError(f"unknown fact_check_profile: {requested}")
        return requested
    if preferred_surface is not None and preferred_surface not in KNOWN_FACT_SURFACES:
        raise ValueError(
            f"unknown surface_context for fact checking: {preferred_surface}; "
            "use a canonical surface or set fact_check_profile explicitly"
        )
    return (
        "instructional_strict"
        if preferred_surface in STRICT_FACT_SURFACES or format_profile == "course"
        else "editorial_materiality"
    )


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
    requested_work_profile = task.get("work_profile")
    work_profile = requested_work_profile or LEGACY_PROFILE_BY_MODE[edit_mode]
    if work_profile not in WORK_PROFILES:
        raise ValueError(f"unknown work_profile: {work_profile}")
    profile = WORK_PROFILES[work_profile]
    if edit_mode not in profile["edit_modes"]:
        raise ValueError(
            f"edit_mode {edit_mode} is not compatible with work_profile {work_profile}"
        )
    requested_source_basis = task.get("source_basis")
    source_basis = requested_source_basis or (
        "sparse_basis" if work_profile == "new_material" else "full_source"
    )
    if source_basis not in SOURCE_BASES:
        raise ValueError(f"unknown source_basis: {source_basis}")
    if source_basis == "sparse_basis" and work_profile != "new_material":
        raise ValueError("sparse_basis requires work_profile new_material")
    if (
        source_basis == "full_source"
        and work_profile == "new_material"
        and edit_mode != "creative_rebuild"
    ):
        raise ValueError("full_source with new_material requires creative_rebuild")
    requested_transcript_role = task.get("transcript_role")
    transcript_role = requested_transcript_role or (
        "article_source" if work_profile == "transcript_to_article" else None
    )
    if transcript_role is not None and transcript_role not in TRANSCRIPT_ROLES:
        raise ValueError(f"unknown transcript_role: {transcript_role}")
    transcript_context = task.get("transcript_context")
    if work_profile == "transcript_to_article" and transcript_role not in {
        "article_source", "video_script"
    }:
        raise ValueError(
            "transcript_to_article requires transcript_role article_source or video_script"
        )
    if transcript_role in {"article_source", "video_script"} and work_profile != "transcript_to_article":
        raise ValueError(
            f"transcript_role {transcript_role} requires work_profile transcript_to_article"
        )
    if transcript_role == "context_only":
        if work_profile == "transcript_to_article":
            raise ValueError("context_only cannot use work_profile transcript_to_article")
        if not isinstance(transcript_context, str) or not transcript_context.strip():
            raise ValueError("task.transcript_context is required for context_only")
    elif transcript_context is not None:
        raise ValueError("task.transcript_context is only valid for transcript_role context_only")
    source_text = task.get("source_text")
    if (
        source_basis == "full_source"
        and work_profile == "new_material"
        and edit_mode == "creative_rebuild"
        and not isinstance(source_text, str)
    ):
        raise ValueError("full_source creative_rebuild requires task.source_text")
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
    preservation_anchors = task.get("preservation_anchors") or []
    if not isinstance(preservation_anchors, list) or any(
        not isinstance(item, str) or not item.strip() for item in preservation_anchors
    ):
        raise ValueError("task.preservation_anchors must be a list of non-empty strings")
    if requested_work_profile and work_profile in {
        "transcript_to_article", "develop_existing"
    } and not preservation_anchors:
        raise ValueError(f"task.preservation_anchors is required for {work_profile}")
    if (
        source_basis == "full_source"
        and work_profile == "new_material"
        and edit_mode == "creative_rebuild"
        and not preservation_anchors
    ):
        raise ValueError("full_source creative_rebuild requires preservation_anchors")
    allowed_removals = task.get("allowed_removals") or []
    if not isinstance(allowed_removals, list) or any(
        not isinstance(item, str) or not item for item in allowed_removals
    ):
        raise ValueError("task.allowed_removals must be a list of exact non-empty fragments")
    structural_labels = task.get("structural_labels") or []
    if not isinstance(structural_labels, list) or any(
        not isinstance(item, str) or not item.strip() for item in structural_labels
    ):
        raise ValueError("task.structural_labels must be a list of exact non-empty headings")
    default_token = float(profile["min_token_coverage"])
    default_length = float(profile["min_length_ratio"])
    min_token_coverage = float(task.get("min_token_coverage", default_token))
    min_length_ratio = float(task.get("min_length_ratio", default_length))
    floor_token, floor_length = profile["floors"]
    if not 0 <= min_token_coverage <= 1 or not 0 <= min_length_ratio <= 1:
        raise ValueError("coverage thresholds must be between 0 and 1")
    if min_token_coverage < floor_token or min_length_ratio < floor_length:
        raise ValueError(
            f"threshold is below the {work_profile} floor; use creative_rebuild"
        )
    if (
        min_token_coverage < default_token or min_length_ratio < default_length
    ) and not allowed_removals:
        raise ValueError("lower thresholds require a non-empty task.allowed_removals ledger")
    required_facts = task.get("required_facts") or []
    if not isinstance(required_facts, list) or any(
        not (
            isinstance(item, str)
            and item.strip()
            or isinstance(item, dict)
            and set(item) <= {"text", "mode"}
            and str(item.get("text") or "").strip()
            and item.get("mode", "semantic") in {"semantic", "verbatim"}
        )
        for item in required_facts
    ):
        raise ValueError(
            "task.required_facts must be a list of non-empty strings or text/mode objects"
        )
    fact_sources = task.get("fact_sources") or []
    if not isinstance(fact_sources, list) or any(
        not isinstance(item, dict)
        or not str(item.get("name") or "").strip()
        or not str(item.get("fingerprint") or "").strip()
        for item in fact_sources
    ):
        raise ValueError("task.fact_sources must contain name and fingerprint")
    if required_facts and not fact_sources:
        raise ValueError("task.fact_sources is required when required_facts is non-empty")
    format_profile = task.get("format_profile")
    if not format_profile:
        if preferred_surface in COURSE_PACKAGE_CONTEXTS:
            format_profile = "course"
        elif preferred_surface in ARTICLE_FORMAT_CONTEXTS:
            format_profile = "article"
    resolved_fact_check_profile = fact_check_profile(
        task, preferred_surface, format_profile
    )
    course_context = task.get("course_context")
    if preferred_surface in COURSE_MATERIAL_CONTEXTS:
        if not isinstance(course_context, dict):
            raise ValueError("task.course_context is required for a course material")
        required_course_fields = {"day_context", "material_role", "continuity"}
        if not required_course_fields.issubset(course_context):
            raise ValueError(
                "task.course_context requires day_context, material_role, and continuity"
            )
        if any(
            not isinstance(course_context.get(field), str)
            or not course_context[field].strip()
            for field in required_course_fields
        ):
            raise ValueError("course_context text fields must be non-empty strings")
    elif course_context is not None:
        raise ValueError("task.course_context is only valid for a course material surface")
    course_continuity = task.get("course_continuity")
    if format_profile != "course" and course_continuity is not None:
        raise ValueError("task.course_continuity is only valid for format_profile course")
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
    requested_block_outline = task.get("block_outline")
    if requested_block_outline is not None and (
        not isinstance(requested_block_outline, list)
        or not requested_block_outline
        or any(not isinstance(item, str) or not item.strip() for item in requested_block_outline)
    ):
        raise ValueError("task.block_outline must be a non-empty list of block topics")
    block_instructions = task.get("block_instructions") or []
    if not isinstance(block_instructions, list) or any(
        not isinstance(item, dict)
        or item.get("action") not in BLOCK_ACTIONS
        or (
            item.get("source") is not None
            and (not isinstance(item.get("source"), str) or not item["source"].strip())
        )
        or (
            item.get("instruction") is not None
            and (
                not isinstance(item.get("instruction"), str)
                or not item["instruction"].strip()
            )
        )
        or (
            item.get("placement") is not None
            and (
                not isinstance(item.get("placement"), str)
                or not item["placement"].strip()
            )
        )
        or (
            item.get("action") != "write_new"
            and not item.get("source")
        )
        or (
            item.get("action") == "write_new"
            and not item.get("instruction")
        )
        for item in block_instructions
    ):
        raise ValueError("task.block_instructions contains an invalid block action")
    if block_instructions and not isinstance(source_text, str):
        raise ValueError("task.source_text is required when block_instructions are used")
    for item in block_instructions:
        source_fragment = item.get("source")
        if source_fragment and source_text.count(source_fragment) != 1:
            raise ValueError(
                "each block_instructions source fragment must occur exactly once"
            )
    addressed_fragments = [
        item["source"] for item in block_instructions if item.get("source")
    ]
    if len(addressed_fragments) != len(set(addressed_fragments)):
        raise ValueError(
            "each source fragment may have only one block_instructions action"
        )
    if edit_mode in {"proofread", "structure_only"} and any(
        item["action"] != "verbatim"
        for item in block_instructions
    ):
        raise ValueError(
            f"substantive block_instructions require rewrite before {edit_mode}"
        )
    for item in block_instructions:
        if item["action"] == "remove" and item["source"] not in allowed_removals:
            allowed_removals.append(item["source"])
    marketing_brief = task.get("marketing_brief")
    if marketing_brief is not None and (
        not isinstance(marketing_brief, dict) or not marketing_brief
    ):
        raise ValueError("task.marketing_brief must be a non-empty object")
    known_marketing_fields = {
        "audience_segment", "promise", "offer", "path",
        "disclosure_boundary", "cta", "success_metric",
    }
    if isinstance(marketing_brief, dict) and any(
        key in marketing_brief
        and (
            not isinstance(marketing_brief[key], str)
            or not marketing_brief[key].strip()
        )
        for key in known_marketing_fields
    ):
        raise ValueError(
            "known task.marketing_brief fields must be non-empty strings"
        )
    requested_author_reuse_mode = task.get("author_reuse_mode")
    if requested_author_reuse_mode is not None and requested_author_reuse_mode not in AUTHOR_REUSE_MODES:
        raise ValueError(f"unknown author_reuse_mode: {requested_author_reuse_mode}")
    if requested_author_reuse_mode:
        author_reuse_mode = requested_author_reuse_mode
        author_reuse_mode_source = "explicit"
    elif preferred_surface in ORIGINAL_COMPOSITION_CONTEXTS:
        author_reuse_mode = "original_composition"
        author_reuse_mode_source = "surface_default"
    elif preferred_surface in COURSE_MATERIAL_CONTEXTS | COURSE_PACKAGE_CONTEXTS or requested_block_outline:
        author_reuse_mode = "authored_blocks_first"
        author_reuse_mode_source = "foundational_default"
    else:
        author_reuse_mode = "original_composition"
        author_reuse_mode_source = "general_default"
    if author_reuse_mode == "authored_blocks_first":
        if requested_block_outline:
            block_outline = [item.strip() for item in requested_block_outline]
            block_outline_source = "explicit"
        else:
            argument_blocks = [
                item.strip()
                for item in (task.get("argument_route") or [])
                if isinstance(item, str) and item.strip()
            ]
            if argument_blocks:
                block_outline = argument_blocks
                block_outline_source = "argument_route"
            elif format_profile == "course" and isinstance(course_outline, list):
                block_outline = [
                    f"День {day['day']}: {material}"
                    for day in course_outline
                    for material in day["materials"]
                ]
                block_outline_source = "course_outline"
            else:
                block_outline = [note]
                block_outline_source = "note_fallback"
    else:
        block_outline = []
        block_outline_source = None
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
        "authored_reuse": {},
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
        authored_reuse = (
            authored_reuse_retrieval(
                index_path,
                block_outline,
                preferred_surface=preferred_surface,
                character_budget=retrieval_profile["full_text_characters"],
                candidates_per_block=2,
            )
            if author_reuse_mode == "authored_blocks_first"
            else {}
        )
        authored_blocked_versions = {
            value
            for block in (authored_reuse.get("blocks") or [])
            for row in block.get("candidates") or []
            for value in [
                row.get("catalog_id"),
                *(row.get("related_versions") or []),
                *(row.get("exact_cluster_ids") or []),
            ]
            if value
        }
        authored_characters = sum(
            len(str(row.get("full_text") or ""))
            for row in (authored_reuse.get("sources") or [])
        )
        remaining_full_text_budget = max(
            0,
            retrieval_profile["full_text_characters"] - authored_characters,
        )
        exemplar_candidates = search_index(
            index_path, query, kind_filter="exemplar", job=job,
            preferred_surface=preferred_surface,
            limit=max(10, retrieval_profile["exemplars"] * 5),
            include_full_text=True,
        )["results"]
        exemplar_selection = distinct_version_groups(
            exemplar_candidates,
            retrieval_profile["exemplars"],
            authored_blocked_versions,
        )
        exemplars = (
            bounded_full_text(
                exemplar_selection,
                ("full_text",),
                remaining_full_text_budget,
            )
            if remaining_full_text_budget
            else []
        )
        blocked_versions = authored_blocked_versions | {
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
        remaining_correction_budget = max(
            0,
            remaining_full_text_budget
            - sum(len(str(row.get("full_text") or "")) for row in exemplars),
        )
        retrieval = {
            "exemplars": exemplars,
            "rhetoric": rhetoric_results[:retrieval_profile["rhetoric"]],
            "corrections": bounded_full_text(
                corrections, ("full_case",), remaining_correction_budget
            ) if remaining_correction_budget else [],
            "rules": search_index(
                index_path, query, kind_filter="rule", limit=retrieval_profile["rules"]
            )["results"],
            "topic_history": distinct_version_groups(
                history_candidates, retrieval_profile["history"], blocked_versions
            ),
            "authored_reuse": authored_reuse,
        }
        if task.get("include_unreviewed_candidates"):
            retrieval["unreviewed_candidates"] = search_index(
                index_path, query, kind_filter="candidate", job=job, limit=8
            )["results"]
    runtime_sources = {
        "authoring_skill": "content/author-voice/skill/edabalans-writer/SKILL.md",
        "work_profiles": "content/author-voice/authoring-work-profiles-v1.md",
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
    if format_profile in {"article", "course"} and (
        task.get("legacy_article_migration") or task.get("visual_contract_change")
    ):
        runtime_sources["article_standard"] = "docs/knowledge-base/ARTICLE_STANDARD.md"
    if format_profile in {"article", "course"} and task.get("article_components"):
        runtime_sources["component_router"] = "content/author-voice/article-component-router.md"
    if format_profile == "course":
        course_structure_source = task.get("course_structure_source")
        if not course_structure_source and preferred_surface == "masterclass_course":
            course_structure_source = "docs/knowledge-base/modules/masterclass/COURSE_STRUCTURE_CONTRACT.md"
        if not course_structure_source:
            raise ValueError("task.course_structure_source is required for a non-Masterclass full course")
        if not isinstance(course_continuity, list) or not course_continuity:
            raise ValueError("task.course_continuity is required for a full course")
        if any(
            not isinstance(item, dict)
            or set(item) != {"idea", "route"}
            or not str(item.get("idea") or "").strip()
            or not str(item.get("route") or "").strip()
            for item in course_continuity
        ):
            raise ValueError("course_continuity items require non-empty idea and route")
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
            "required_facts": required_facts,
            "fact_check_profile": resolved_fact_check_profile,
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
            "work_profile": work_profile,
            "work_profile_source": "explicit" if requested_work_profile else "inferred",
            "source_basis": source_basis,
            "source_basis_source": "explicit" if requested_source_basis else "inferred",
            "author_reuse_mode": author_reuse_mode,
            "author_reuse_mode_source": author_reuse_mode_source,
            "block_outline": block_outline,
            "block_outline_source": block_outline_source,
            "block_instructions": block_instructions,
            "marketing_brief": marketing_brief,
            "transcript_role": transcript_role,
            "transcript_role_source": (
                "explicit" if requested_transcript_role else (
                    "legacy_default" if transcript_role else None
                )
            ),
            "transcript_context": transcript_context,
            "course_context": course_context,
            "course_continuity": course_continuity,
            "source_text": source_text,
            "protected_text": task.get("protected_text"),
            "editable_scope": editable_scope,
            "rewrite_goal": rewrite_goal,
            "preservation_anchors": preservation_anchors,
            "allowed_removals": allowed_removals,
            "structural_labels": structural_labels,
            "min_token_coverage": min_token_coverage,
            "min_length_ratio": min_length_ratio,
            "fact_sources": fact_sources,
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
            (
                "Use retrieval.authored_reuse block by block: reuse a strong authored block verbatim or with edge-only edits, and write new prose only for a confirmed gap."
                if author_reuse_mode == "authored_blocks_first"
                else "Use retrieved material as source-linked patterns; do not transplant old blocks automatically."
            ),
            "Build the emotion and argument route before drafting sentences.",
            "Apply editing permissions from editing-modes-v1.md without widening them.",
            *(
                ["Apply every block_instructions action independently. Verbatim blocks are exact; unmarked accepted author blocks stay unchanged or receive only the minimum edit required by the task."]
                if block_instructions
                else []
            ),
            "For a site article or course material, apply ARTICLE_STANDARD.md; never invent headings only to create a table of contents.",
            "Apply the review policy owned by the selected normative contract.",
            (
                "Return a clean continuous text without an automatic suggestion appendix."
                if source_basis == "full_source"
                else
                "Return a complete publishable text plus a clearly non-publishable owner-review note with ready extra blocks, visuals, the weakest block, and material owner questions."
            ),
            (
                "Treat the transcript as context only: use it to avoid duplication and understand the neighboring material; do not copy its wording into the target automatically."
                if transcript_role == "context_only"
                else "Preserve the transcript as the authored source for the selected article or video-script output."
                if transcript_role in {"article_source", "video_script"}
                else "No transcript role applies."
            ),
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
            "fact_check_profile": resolved_fact_check_profile,
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
