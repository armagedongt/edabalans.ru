"""Validate and idempotently import the sealed local authoring catalog.

The source directory stays outside Git. Dry-run is the default; applying data requires
an explicit fresh-backup acknowledgement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


EXPECTED_SOURCES = {"telegram_main", "bot", "telegraph", "pikabu", "pikabu_reply"}
SOURCE_CONFIG = {
    "telegram_main": ("telegram", "1878297271", "Fitness Talks", "https://t.me/Fitness_Talks"),
    "bot": ("leadteh", "245278", "LeadTeh bot 245278", "https://app.leadteh.ru/bots/245278/schema"),
    "telegraph": ("telegraph", "edabalans", "Telegraph", "https://telegra.ph"),
    "pikabu": ("pikabu", "armagedongt", "armagedongt", "https://pikabu.ru/@armagedongt"),
    "pikabu_reply": ("pikabu", "armagedongt", "armagedongt", "https://pikabu.ru/@armagedongt"),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path.name}:{line_no} is not an object")
            rows.append(value)
    return rows


def load_snapshot(root: Path) -> tuple[list[dict], list[dict], dict, dict]:
    required = ["catalog.jsonl", "family-review-candidates.jsonl", "family-review-decisions.json", "report.json"]
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise ValueError(f"missing snapshot files: {', '.join(missing)}")
    items = read_jsonl(root / "catalog.jsonl")
    pairs = read_jsonl(root / "family-review-candidates.jsonl")
    decisions = json.loads((root / "family-review-decisions.json").read_text(encoding="utf-8"))
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    return items, pairs, decisions, report


def _snapshot_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for name in ("catalog.jsonl", "family-review-candidates.jsonl", "family-review-decisions.json", "report.json"):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_snapshot(root: Path) -> dict[str, Any]:
    items, pairs, decisions, report = load_snapshot(root)
    ids = [str(row.get("id") or "") for row in items]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("catalog ids must be present and unique")
    sources = {str(row.get("source") or "") for row in items}
    if sources != EXPECTED_SOURCES:
        raise ValueError(f"unexpected sources: {sorted(sources)}")
    active = [row for row in items if (row.get("control") or {}).get("status", "active") == "active"]
    by_source = {source: sum(1 for row in active if row.get("source") == source) for source in EXPECTED_SOURCES}
    if by_source != report.get("working_by_source"):
        raise ValueError("active source counts differ from report")
    if len(active) != int(report.get("active_manifestations") or 0):
        raise ValueError("active manifestation count differs from report")
    family_ids = {str((row.get("control") or {}).get("family_id") or row.get("family_id") or "") for row in active}
    family_ids.discard("")
    if len(family_ids) != int(report.get("families") or 0):
        raise ValueError("family count differs from report")
    singletons = sum(not ((row.get("control") or {}).get("family_id") or row.get("family_id")) for row in active)
    if singletons != int(report.get("singletons") or 0):
        raise ValueError("singleton count differs from report")
    known = set(ids)
    for pair in pairs:
        if pair.get("left") not in known or pair.get("right") not in known:
            raise ValueError("candidate points outside catalog")
    rejected = decisions.get("rejected_pair_keys") or []
    if not isinstance(rejected, list) or not all(isinstance(value, str) for value in rejected):
        raise ValueError("invalid family decisions")
    with_media = sum(bool((row.get("media") or {}).get("present")) for row in active)
    if with_media != int(report.get("with_media") or 0):
        raise ValueError("media count differs from report")
    pending_pairs = [pair for pair in pairs if _local_decision_key(pair) not in set(rejected)]
    parent: dict[str, str] = {}
    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]
    for pair in pending_pairs:
        left, right = str(pair["left"]), str(pair["right"])
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a
    candidate_groups = len({find(value) for value in parent})
    if candidate_groups != int(report.get("family_review_candidates") or 0):
        raise ValueError("candidate group count differs from report")
    return {
        "manifestations": len(active),
        "families": len(family_ids),
        "singletons": singletons,
        "candidate_pairs": len(pairs),
        "candidate_groups": candidate_groups,
        "with_media": with_media,
        "by_source": by_source,
        "snapshot_digest": _snapshot_digest(root),
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _version_hash(row: dict) -> str:
    control = row.get("control") or {}
    body = json.dumps(
        {
            "title": row.get("title") or "",
            "text": row.get("text") or "",
            "metadata": {
                "variant_label": control.get("variant_label") or "",
                "editorial_status": control.get("status") or "active",
                "catalog_key": row.get("id"),
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _media_rows(row: dict) -> list[dict]:
    media = row.get("media") or {}
    values = []
    seen = set()
    for item in media.get("items") or []:
        url = item.get("source_url") or item.get("preview_url")
        key = (item.get("media_type") or "other", url)
        if key in seen:
            continue
        seen.add(key)
        values.append({
            "media_type": item.get("media_type") or "other",
            "source_url": item.get("source_url"),
            "preview_url": item.get("preview_url"),
            "metadata_json": {"catalog_media": media},
        })
    for link in media.get("links") or []:
        url = link.get("url")
        key = ("image", url)
        if not url or key in seen:
            continue
        seen.add(key)
        values.append({"media_type": "image", "source_url": url, "preview_url": None, "metadata_json": {"catalog_media": media}})
    if media.get("present") and not values:
        file_value = media.get("file") or media.get("path")
        source_url = str(file_value) if file_value and str(file_value).startswith(("http://", "https://")) else None
        values.append({"media_type": media.get("kind") or "other", "source_url": source_url, "preview_url": None, "metadata_json": {"catalog_media": media, "source_locator": file_value}})
    return values


def _pair_key(left: str, right: str) -> str:
    return "|".join(sorted((left, right)))


def _local_decision_key(pair: dict) -> str:
    left, right = sorted((str(pair.get("left") or ""), str(pair.get("right") or "")))
    value = f"{left}|{right}|{pair.get('method') or ''}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def import_snapshot(
    root: Path,
    *,
    apply: bool,
    backup_confirmed: bool = False,
    expected_digest: str | None = None,
) -> dict:
    validation = validate_snapshot(root)
    if expected_digest and validation["snapshot_digest"] != expected_digest:
        raise ValueError("snapshot digest differs from --expected-digest")
    if not apply:
        return {"mode": "dry-run", **validation}
    if not backup_confirmed:
        raise ValueError("--backup-confirmed is required for apply")
    if not expected_digest:
        raise ValueError("--expected-digest is required for apply")

    from sqlalchemy import func, select
    from app.database import SessionLocal
    from app.models import (
        ContentFamily,
        ContentFamilyCandidate,
        ContentFamilyMembership,
        ContentImportRun,
        ContentItem,
        ContentItemVersion,
        ContentLink,
        ContentMedia,
        ContentSource,
    )

    items, pairs, decisions, _report = load_snapshot(root)
    result = {"mode": "apply", **validation, "created": 0, "matched": 0, "versions_created": 0, "memberships_created": 0, "candidates_created": 0}
    with SessionLocal() as db:
        source_cache = {}
        for catalog_source, config in SOURCE_CONFIG.items():
            platform, account_key, display_name, canonical_url = config
            source = db.scalar(select(ContentSource).where(ContentSource.platform == platform, ContentSource.account_key == account_key))
            if source is None:
                source = ContentSource(platform=platform, account_key=account_key, display_name=display_name, canonical_url=canonical_url)
                db.add(source)
                db.flush()
            source_cache[catalog_source] = source

        by_catalog_key = {}
        for row in items:
            catalog_key = str(row["id"])
            source = source_cache[str(row["source"])]
            item = db.scalar(select(ContentItem).where(ContentItem.catalog_key == catalog_key))
            if item is None:
                item = db.scalar(select(ContentItem).where(ContentItem.source_id == source.id, ContentItem.external_id == str(row["external_id"])))
            created = item is None
            if item is None:
                item = ContentItem(source_id=source.id, external_id=str(row["external_id"]), canonical_url=str(row.get("source_url") or ""), title=str(row.get("title") or catalog_key))
                db.add(item)
                db.flush()
            current_version = db.get(ContentItemVersion, item.latest_version_id) if item.latest_version_id else None
            owner_latest = bool(current_version and current_version.parser_version == "owner-edit-v1")
            control = row.get("control") or {}
            item.catalog_key = catalog_key
            item.canonical_url = str(row.get("source_url") or item.canonical_url or "")
            if not owner_latest:
                item.title = str(row.get("title") or catalog_key).strip()
            item.published_at = _parse_datetime(row.get("published_at"))
            item.status = "published"
            item.manifestation_kind = "reply" if row["source"] == "pikabu_reply" else "post"
            if not owner_latest:
                item.editorial_status = str(control.get("status") or "active")
            item.purpose = str(row.get("purpose") or "ordinary_content")
            item.sales_level = str(row.get("sales_level") or control.get("sales_level") or "none")
            item.meanings = row.get("meanings") or []
            item.topics = row.get("topics") or []
            item.primary_function = row.get("primary_function")
            if not owner_latest:
                item.variant_label = str(control.get("variant_label") or "")
            item.metadata_json = {"catalog_provenance": row.get("provenance") or {}, "roles": row.get("roles") or [], "media": row.get("media") or {}}

            content_hash = _version_hash(row)
            version = db.scalar(select(ContentItemVersion).where(ContentItemVersion.item_id == item.id, ContentItemVersion.content_hash == content_hash))
            if version is None:
                next_no = (db.scalar(select(func.max(ContentItemVersion.version_no)).where(ContentItemVersion.item_id == item.id)) or 0) + 1
                version = ContentItemVersion(item_id=item.id, version_no=next_no, content_hash=content_hash, text_content=str(row.get("text") or "").strip(), blocks=[], parser_version="local-content-catalog-v1", editorial_metadata={"title": item.title, "variant_label": item.variant_label, "editorial_status": item.editorial_status, "catalog_key": catalog_key})
                db.add(version)
                db.flush()
                for position, media in enumerate(_media_rows(row)):
                    db.add(ContentMedia(item_id=item.id, version_id=version.id, position=position, **media))
                for position, url in enumerate((row.get("provenance") or {}).get("outbound_urls") or []):
                    parsed = urlparse(str(url))
                    db.add(ContentLink(item_id=item.id, version_id=version.id, visible_text=None, wrapped_url=str(url), target_url=str(url), domain=parsed.hostname, link_type="other", is_cta=False, ignored_for_generation=False, position=position))
                result["versions_created"] += 1
            if not owner_latest:
                item.latest_version_id = version.id
            by_catalog_key[catalog_key] = item
            result["created" if created else "matched"] += 1

        family_cache = {}
        for row in items:
            family_key = str((row.get("control") or {}).get("family_id") or row.get("family_id") or "")
            if not family_key:
                continue
            family = family_cache.get(family_key) or db.scalar(select(ContentFamily).where(ContentFamily.family_key == family_key))
            if family is None:
                family = ContentFamily(family_key=family_key)
                db.add(family)
                db.flush()
            family_cache[family_key] = family
            item = by_catalog_key[str(row["id"])]
            membership = db.get(ContentFamilyMembership, item.id)
            if membership is None:
                db.add(ContentFamilyMembership(item_id=item.id, family_id=family.id))
                result["memberships_created"] += 1

        rejected_keys = set(decisions.get("rejected_pair_keys") or [])
        for pair in pairs:
            left_key, right_key = str(pair["left"]), str(pair["right"])
            left, right = by_catalog_key[left_key], by_catalog_key[right_key]
            if str(left.id) > str(right.id):
                left, right = right, left
            key = _pair_key(left_key, right_key)
            candidate = db.get(ContentFamilyCandidate, key)
            locally_rejected = _local_decision_key(pair) in rejected_keys
            if candidate is None:
                candidate = ContentFamilyCandidate(pair_key=key, left_item_id=left.id, right_item_id=right.id, method=str(pair.get("method") or "unknown"), shared_tokens=pair.get("shared_tokens"), status="rejected" if locally_rejected else "pending", metadata_json={"catalog_left": left_key, "catalog_right": right_key})
                db.add(candidate)
                result["candidates_created"] += 1
            elif locally_rejected and candidate.status == "pending":
                candidate.status = "rejected"
                candidate.decided_at = datetime.now(timezone.utc)

        db.add(ContentImportRun(source_id=None, mode="local_catalog", status="completed", parser_version="local-content-catalog-v1", finished_at=datetime.now(timezone.utc), summary=result))
        db.commit()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    parser.add_argument("--expected-digest")
    args = parser.parse_args()
    print(json.dumps(import_snapshot(args.catalog.resolve(), apply=args.apply, backup_confirmed=args.backup_confirmed, expected_digest=args.expected_digest), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
