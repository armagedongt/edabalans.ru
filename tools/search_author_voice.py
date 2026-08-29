"""Search the private author-voice exemplar and rhetorical-fragment index."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("voice index must stay outside Git")
    return resolved


ITEM_TABLES = {
    "rule": ("rules", "rule_id"),
    "exemplar": ("exemplars", "exemplar_id"),
    "fragment": ("fragments", "fragment_id"),
    "candidate": ("fragments", "fragment_id"),
    "rhetoric": ("rhetoric", "entry_id"),
    "correction": ("corrections", "correction_id"),
    "corpus": ("corpus", "corpus_id"),
}


def get_index_item(index: Path, item_id: str, *, include_full_text: bool = False) -> dict:
    """Fetch one exact indexed item after a compact search selected its ID."""
    index = private(index)
    with closing(sqlite3.connect(index)) as db:
        match = db.execute(
            "SELECT kind, catalog_id FROM voice_fts WHERE item_id = ? LIMIT 1",
            (item_id,),
        ).fetchone()
        if not match:
            raise ValueError(f"voice item not found: {item_id}")
        kind, catalog_id = match
        table, key = ITEM_TABLES[kind]
        payload = db.execute(
            f"SELECT payload_json FROM {table} WHERE {key} = ?",
            (item_id,),
        ).fetchone()
        if not payload:
            raise ValueError(f"voice item payload not found: {item_id}")
    row = json.loads(payload[0])
    result = {
        "kind": kind,
        "item_id": item_id,
        "catalog_id": catalog_id,
        "source": row.get("source"),
        "source_url": row.get("source_url"),
        "headline": row.get("headline"),
    }
    if include_full_text:
        result["full_text"] = (
            row.get("full_case") if kind == "correction" else row.get("text")
        )
    return result


def matches(
    row: dict,
    job: str | None,
    surface: str | None,
    slot: str | None,
    family: str | None,
) -> bool:
    if job and row.get("dominant_job") != job:
        return False
    if surface and row.get("surface_context") != surface:
        return False
    if slot and row.get("fragment_kind") != slot and slot not in (row.get("composition_map") or row.get("composition_recipe") or []):
        return False
    if family and row.get("family") != family:
        return False
    return True


def natural_fts_query(value: str) -> str:
    """Turn ordinary Russian text into a safe broad FTS prefix query."""
    stopwords = {
        "для", "про", "или", "как", "где", "что", "это", "мне", "надо",
        "нужен", "нужна", "нужно", "пост", "текст", "сообщение", "вариант",
    }
    tokens = [
        token.casefold()
        for token in re.findall(r"[\wёЁ]+", value, flags=re.UNICODE)
        if len(token) >= 3 and token.casefold() not in stopwords
    ]
    if not tokens:
        raise ValueError("search query has no meaningful words")
    suffixes = (
        "ениями", "ение", "ения", "ению", "ений", "остью", "ости",
        "овать", "ывать", "ивать", "аться", "яться", "еться", "иться",
        "ать", "ять", "еть", "ить", "ого", "ему", "ами", "ями",
        "ов", "ев", "ей", "ам", "ям", "ах", "ях", "ся", "ы", "и",
        "а", "я", "у", "ю", "е", "о",
    )
    variants: list[str] = []
    for token in tokens:
        variants.append(token)
        stem = next(
            (token[:-len(suffix)] for suffix in suffixes if token.endswith(suffix) and len(token) - len(suffix) >= 4),
            token,
        )
        variants.append(stem)
    return " OR ".join(f'"{token}"*' for token in dict.fromkeys(variants))


def search_index(
    index: Path,
    query: str,
    *,
    kind_filter: str = "all",
    job: str | None = None,
    surface: str | None = None,
    slot: str | None = None,
    family: str | None = None,
    preferred_surface: str | None = None,
    exclude_technical: bool = False,
    limit: int = 8,
    raw_fts: bool = False,
    include_full_text: bool = False,
) -> dict:
    index = private(index)
    fts_query = query if raw_fts else natural_fts_query(query)
    where = ["voice_fts MATCH ?"]
    params: list[object] = [fts_query]
    if kind_filter != "all":
        where.append("kind = ?")
        params.append(kind_filter)
    else:
        where.append("kind NOT IN ('candidate', 'corpus')")
    sql = f"""
        SELECT kind, item_id, catalog_id,
               snippet(voice_fts, 4, '[', ']', ' … ', 32) AS excerpt,
               bm25(voice_fts) AS lexical_score
        FROM voice_fts
        WHERE {' AND '.join(where)}
        ORDER BY bm25(voice_fts)
    """
    results: list[dict] = []
    with closing(sqlite3.connect(index)) as db:
        for kind, item_id, catalog_id, excerpt, lexical_score in db.execute(sql, params):
            table, key = ITEM_TABLES[kind]
            payload = db.execute(f"SELECT payload_json FROM {table} WHERE {key} = ?", (item_id,)).fetchone()
            if not payload:
                continue
            row = json.loads(payload[0])
            if not matches(row, job, surface, slot, family):
                continue
            if exclude_technical and row.get("corpus_usability") == "technical_template":
                continue
            strength_bonus = {
                "owner_named_core": 3.0,
                "current_core": 1.5,
                "current_sales_core": 1.5,
                "system_core": 1.5,
                "high_response_core": 1.0,
                "supporting": 0.25,
                "sales_supporting": 0.25,
                "platform_variant": 0.25,
            }.get(row.get("strength"), 0.0)
            surface_bonus = 0.75 if preferred_surface and row.get("surface_context") == preferred_surface else 0.0
            result = {
                "kind": kind,
                "item_id": item_id,
                "catalog_id": catalog_id,
                "source": row.get("source"),
                "source_url": row.get("source_url"),
                "headline": row.get("headline"),
                "dominant_job": row.get("dominant_job"),
                "surface_context": row.get("surface_context"),
                "fragment_kind": row.get("fragment_kind"),
                "rhetorical_family": row.get("family"),
                "rhetorical_subtype": row.get("subtype"),
                "rhetorical_function": row.get("function"),
                "reuse_instruction": row.get("reuse_instruction"),
                "works_when": row.get("works_when") or [],
                "avoid_when": row.get("avoid_when") or [],
                "composition": row.get("composition_map") or row.get("composition_recipe"),
                "strength": row.get("strength"),
                "related_versions": row.get("related_versions") or [],
                "exact_cluster_ids": row.get("exact_cluster_ids") or [],
                "corpus_usability": row.get("corpus_usability"),
                "excerpt": excerpt,
                "text": row.get("text") if kind in {"rhetoric", "candidate", "fragment"} else None,
                "context_before": row.get("context_before"),
                "context_after": row.get("context_after"),
                "mechanism": row.get("mechanism"),
                "cluster_id": row.get("cluster_id"),
                "limitations": row.get("limitations") or [],
                "media_dependency": row.get("media_dependency"),
                "media_note": row.get("media_note"),
                "media_hypothesis": row.get("media_hypothesis"),
                "performance_signals": row.get("performance_signals") or {},
                "rule_statement": row.get("statement"),
                "correction_title": row.get("title") if kind == "correction" else None,
                "lexical_score": lexical_score,
                "_strength_bonus": strength_bonus,
                "_surface_bonus": surface_bonus,
            }
            if include_full_text:
                if kind in {"exemplar", "corpus"}:
                    result["full_text"] = row.get("text")
                elif kind == "correction":
                    result["full_case"] = row.get("full_case")
            results.append(result)
    if results:
        best_lexical = min(row["lexical_score"] for row in results)
        worst_lexical = max(row["lexical_score"] for row in results)
        lexical_span = worst_lexical - best_lexical
        for lexical_rank, row in enumerate(sorted(results, key=lambda item: (item["lexical_score"], item["item_id"]))):
            row["lexical_rank"] = lexical_rank
            lexical_cost = 0.0 if lexical_span <= 1e-12 else 10.0 * (row["lexical_score"] - best_lexical) / lexical_span
            row["ranking_score"] = lexical_cost - row.pop("_strength_bonus") - row.pop("_surface_bonus")
    results.sort(key=lambda row: (row["ranking_score"], row["lexical_rank"], row["item_id"]))
    results = results[:limit]
    return {
        "query": query,
        "fts_query": fts_query,
        "filters": {"kind": kind_filter, "job": job, "surface": surface, "preferred_surface": preferred_surface, "exclude_technical": exclude_technical, "slot": slot, "family": family},
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", help="Ordinary search phrase in Russian")
    parser.add_argument("--item-id", help="Fetch one exact search result by item_id")
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--kind", choices=("all", "rule", "exemplar", "rhetoric", "candidate", "fragment", "correction", "corpus"), default="all")
    parser.add_argument("--job", choices=("education", "personal", "engagement", "sales", "navigation"))
    parser.add_argument("--surface")
    parser.add_argument("--slot")
    parser.add_argument("--family")
    parser.add_argument("--preferred-surface")
    parser.add_argument("--exclude-technical", action="store_true")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--raw-fts", action="store_true", help="Treat query as expert SQLite FTS syntax")
    parser.add_argument("--include-full-text", action="store_true")
    args = parser.parse_args()
    if bool(args.query) == bool(args.item_id):
        parser.error("provide exactly one of query or --item-id")
    payload = (
        get_index_item(
            args.index,
            args.item_id,
            include_full_text=args.include_full_text,
        )
        if args.item_id
        else search_index(
            args.index, args.query, kind_filter=args.kind, job=args.job,
            surface=args.surface, slot=args.slot, family=args.family,
            preferred_surface=args.preferred_surface,
            exclude_technical=args.exclude_technical,
            limit=args.limit, raw_fts=args.raw_fts,
            include_full_text=args.include_full_text,
        )
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
