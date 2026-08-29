from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ContentFamily,
    ContentFamilyCandidate,
    ContentFamilyMembership,
    ContentItem,
    ContentItemVersion,
    ContentLink,
    ContentMedia,
    ContentSource,
)


class RevisionConflict(ValueError):
    pass


def _source_label(source: ContentSource, item: ContentItem) -> str:
    if source.platform == "leadteh":
        return "Бот"
    if source.platform == "telegraph":
        return "Telegraph"
    if source.platform == "pikabu" and item.manifestation_kind == "reply":
        return "Ответ Pikabu"
    if source.platform == "pikabu":
        return "Pikabu"
    if source.platform == "telegram":
        return "Telegram"
    return source.display_name


def _snippet(text: str, length: int = 240) -> str:
    compact = " ".join((text or "").split())
    return compact if len(compact) <= length else compact[: length - 1].rstrip() + "…"


def _date_key(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _item_payload(db: Session, item: ContentItem, source: ContentSource) -> dict:
    version = db.get(ContentItemVersion, item.latest_version_id) if item.latest_version_id else None
    media = []
    links = []
    if version:
        media = db.scalars(
            select(ContentMedia).where(ContentMedia.version_id == version.id).order_by(ContentMedia.position)
        ).all()
        links = db.scalars(
            select(ContentLink).where(ContentLink.version_id == version.id).order_by(ContentLink.position)
        ).all()
    return {
        "id": str(item.id),
        "catalog_key": item.catalog_key,
        "source": source.platform,
        "source_label": _source_label(source, item),
        "manifestation_kind": item.manifestation_kind,
        "external_id": item.external_id,
        "canonical_url": item.canonical_url,
        "title": item.title,
        "text": version.text_content if version else "",
        "revision": version.version_no if version else 0,
        "variant_label": item.variant_label,
        "editorial_status": item.editorial_status,
        "published_at": item.published_at,
        "purpose": item.purpose,
        "sales_level": item.sales_level,
        "meanings": item.meanings,
        "topics": item.topics,
        "primary_function": item.primary_function,
        "metadata": item.metadata_json,
        "media": [
            {
                "type": row.media_type,
                "source_url": row.source_url,
                "preview_url": row.preview_url,
                "position": row.position,
                "metadata": row.metadata_json,
            }
            for row in media
        ],
        "links": [
            {"text": row.visible_text, "url": row.target_url, "type": row.link_type}
            for row in links
        ],
    }


def _working_rows(db: Session) -> list[tuple[ContentItem, ContentSource, ContentFamilyMembership | None]]:
    return db.execute(
        select(ContentItem, ContentSource, ContentFamilyMembership)
        .join(ContentSource, ContentSource.id == ContentItem.source_id)
        .outerjoin(ContentFamilyMembership, ContentFamilyMembership.item_id == ContentItem.id)
        .where(ContentItem.catalog_key.is_not(None))
    ).all()


def authoring_summary(db: Session) -> dict:
    rows = _working_rows(db)
    active = [row for row in rows if row[0].editorial_status == "active"]
    families = {row[2].family_id for row in active if row[2]}
    family_items = sum(1 for row in active if row[2])
    pending_pairs = db.scalars(
        select(ContentFamilyCandidate).where(ContentFamilyCandidate.status == "pending")
    ).all()
    return {
        "manifestations": len(active),
        "removed": len(rows) - len(active),
        "families": len(families),
        "singletons": len(active) - family_items,
        "candidate_groups": len(_candidate_components(db, pending_pairs)),
        "by_source": dict(
            sorted(
                (key, sum(1 for item, source, _ in active if source.platform == key))
                for key in {source.platform for _, source, _ in active}
            )
        ),
    }


def list_authoring_groups(
    db: Session,
    *,
    q: str = "",
    source: str = "",
    shape: str = "all",
    purpose: str = "",
    editorial_status: str = "active",
    offset: int = 0,
    limit: int = 10,
) -> dict:
    grouped: dict[str, list[tuple[ContentItem, ContentSource]]] = defaultdict(list)
    working_rows = _working_rows(db)
    latest_ids = {item.latest_version_id for item, _, _ in working_rows if item.latest_version_id}
    versions = {
        version.id: version
        for version in db.scalars(
            select(ContentItemVersion).where(ContentItemVersion.id.in_(latest_ids))
        ).all()
    } if latest_ids else {}
    for item, src, membership in working_rows:
        if editorial_status != "all" and item.editorial_status != editorial_status:
            continue
        key = f"family:{membership.family_id}" if membership else f"singleton:{item.id}"
        grouped[key].append((item, src))
    needle = q.strip().casefold()
    result = []
    for key, members in grouped.items():
        is_family = key.startswith("family:")
        if shape == "families" and not is_family:
            continue
        if shape == "singletons" and is_family:
            continue
        if source and not any(row[1].platform == source for row in members):
            continue
        if purpose and not any(row[0].purpose == purpose for row in members):
            continue
        if needle and not any(needle in f"{row[0].title} {row[0].external_id}".casefold() for row in members):
            continue
        members.sort(key=lambda row: (_date_key(row[0].published_at), row[0].title))
        first, first_source = members[0]
        version = versions.get(first.latest_version_id)
        result.append({
            "key": key,
            "title": first.title,
            "snippet": _snippet(version.text_content if version else ""),
            "is_family": is_family,
            "manifestations": len(members),
            "sources": sorted({_source_label(src, item) for item, src in members}),
            "sales_levels": sorted({item.sales_level for item, _ in members}),
            "published_at": max((item.published_at for item, _ in members if item.published_at), key=_date_key, default=None),
        })
    result.sort(key=lambda row: (_date_key(row["published_at"]), row["title"]), reverse=True)
    return {"total": len(result), "offset": offset, "limit": limit, "groups": result[offset:offset + limit]}


def get_authoring_group(db: Session, group_key: str) -> dict | None:
    if group_key.startswith("family:"):
        try:
            family_id = uuid.UUID(group_key.split(":", 1)[1])
        except ValueError:
            return None
        rows = db.execute(
            select(ContentItem, ContentSource)
            .join(ContentFamilyMembership, ContentFamilyMembership.item_id == ContentItem.id)
            .join(ContentSource, ContentSource.id == ContentItem.source_id)
            .where(ContentFamilyMembership.family_id == family_id)
        ).all()
    elif group_key.startswith("singleton:"):
        try:
            item_id = uuid.UUID(group_key.split(":", 1)[1])
        except ValueError:
            return None
        rows = db.execute(
            select(ContentItem, ContentSource)
            .join(ContentSource, ContentSource.id == ContentItem.source_id)
            .where(ContentItem.id == item_id)
        ).all()
    else:
        return None
    if not rows:
        return None
    return {"key": group_key, "items": [_item_payload(db, item, source) for item, source in rows]}


def _revision_hash(title: str, text: str, metadata: dict) -> str:
    body = json.dumps({"title": title, "text": text, "metadata": metadata}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def save_authoring_item(
    db: Session,
    item_id: uuid.UUID,
    *,
    expected_revision: int,
    title: str,
    text: str,
    variant_label: str,
    editorial_status: str,
) -> dict:
    item = db.scalar(select(ContentItem).where(ContentItem.id == item_id).with_for_update())
    if not item or not item.catalog_key:
        raise LookupError("content item not found")
    current = db.get(ContentItemVersion, item.latest_version_id) if item.latest_version_id else None
    current_revision = current.version_no if current else 0
    if current_revision != expected_revision:
        raise RevisionConflict(f"current revision is {current_revision}")
    title = title.strip()
    text = text.strip()
    variant_label = variant_label.strip()
    if not title or len(title) > 400 or "\n" in title:
        raise ValueError("invalid title")
    if not text or len(text) > 250_000:
        raise ValueError("invalid text")
    if len(variant_label) > 120:
        raise ValueError("invalid variant label")
    if editorial_status not in {"active", "removed"}:
        raise ValueError("invalid editorial status")
    metadata = {
        "title": title,
        "variant_label": variant_label,
        "editorial_status": editorial_status,
        "editor": "owner",
    }
    current_metadata = current.editorial_metadata if current else {}
    if current and current.text_content == text and item.title == title and item.variant_label == variant_label and item.editorial_status == editorial_status and all(current_metadata.get(key) == value for key, value in metadata.items() if key != "editor"):
        source = db.get(ContentSource, item.source_id)
        return _item_payload(db, item, source)
    next_revision = (db.scalar(select(func.max(ContentItemVersion.version_no)).where(ContentItemVersion.item_id == item.id)) or 0) + 1
    content_hash = _revision_hash(title, text, {**metadata, "parent_revision": current_revision, "revision": next_revision})
    version = ContentItemVersion(
        item_id=item.id,
        version_no=next_revision,
        content_hash=content_hash,
        text_content=text,
        blocks=current.blocks if current else [],
        parser_version="owner-edit-v1",
        editorial_metadata=metadata,
    )
    db.add(version)
    db.flush()
    if current:
        for media in db.scalars(select(ContentMedia).where(ContentMedia.version_id == current.id)):
            db.add(ContentMedia(item_id=item.id, version_id=version.id, media_type=media.media_type, source_url=media.source_url, preview_url=media.preview_url, position=media.position, metadata_json=media.metadata_json))
        for link in db.scalars(select(ContentLink).where(ContentLink.version_id == current.id)):
            db.add(ContentLink(item_id=item.id, version_id=version.id, visible_text=link.visible_text, wrapped_url=link.wrapped_url, target_url=link.target_url, domain=link.domain, link_type=link.link_type, is_cta=link.is_cta, ignored_for_generation=link.ignored_for_generation, position=link.position))
    item.title = title
    item.variant_label = variant_label
    item.editorial_status = editorial_status
    item.latest_version_id = version.id
    db.commit()
    source = db.get(ContentSource, item.source_id)
    return _item_payload(db, item, source)


def _candidate_components(db: Session, pairs: list[ContentFamilyCandidate]) -> list[dict]:
    if not pairs:
        return []
    parent: dict[uuid.UUID, uuid.UUID] = {}
    def find(value: uuid.UUID) -> uuid.UUID:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]
    def union(left: uuid.UUID, right: uuid.UUID) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a
    for pair in pairs:
        union(pair.left_item_id, pair.right_item_id)
    grouped_pairs: dict[uuid.UUID, list[ContentFamilyCandidate]] = defaultdict(list)
    for pair in pairs:
        grouped_pairs[find(pair.left_item_id)].append(pair)
    memberships = {row.item_id: row.family_id for row in db.scalars(select(ContentFamilyMembership)).all()}
    family_members: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for item_id, family_id in memberships.items():
        family_members[family_id].add(item_id)
    result = []
    for component in grouped_pairs.values():
        member_ids = {item for pair in component for item in (pair.left_item_id, pair.right_item_id)}
        for item_id in list(member_ids):
            family_id = memberships.get(item_id)
            if family_id:
                member_ids.update(family_members[family_id])
        pair_keys = sorted(pair.pair_key for pair in component)
        result.append({
            "id": "candidate-" + hashlib.sha256("|".join(pair_keys).encode()).hexdigest()[:18],
            "pair_keys": pair_keys,
            "member_ids": sorted(member_ids, key=str),
            "methods": sorted({pair.method for pair in component}),
        })
    return sorted(result, key=lambda row: row["id"])


def list_candidate_groups(db: Session, *, offset: int = 0, limit: int = 10) -> dict:
    pairs = db.scalars(select(ContentFamilyCandidate).where(ContentFamilyCandidate.status == "pending")).all()
    groups = _candidate_components(db, pairs)
    item_ids = {item_id for group in groups[offset:offset + limit] for item_id in group["member_ids"]}
    rows = db.execute(
        select(ContentItem, ContentSource).join(ContentSource, ContentSource.id == ContentItem.source_id).where(ContentItem.id.in_(item_ids))
    ).all() if item_ids else []
    by_id = {item.id: _item_payload(db, item, source) for item, source in rows}
    page = []
    for group in groups[offset:offset + limit]:
        page.append({**group, "member_ids": [str(item_id) for item_id in group["member_ids"]], "items": [by_id[item_id] for item_id in group["member_ids"] if item_id in by_id]})
    return {"total": len(groups), "offset": offset, "limit": limit, "groups": page}


def decide_candidate_group(
    db: Session,
    *,
    candidate_id: str,
    pair_keys: list[str],
    action: str,
    selected_ids: list[uuid.UUID],
) -> dict:
    pending = db.scalars(
        select(ContentFamilyCandidate).where(
            ContentFamilyCandidate.pair_key.in_(pair_keys),
            ContentFamilyCandidate.status == "pending",
        ).with_for_update()
    ).all()
    components = _candidate_components(db, pending)
    group = next((row for row in components if row["id"] == candidate_id and row["pair_keys"] == sorted(pair_keys)), None)
    if not group:
        raise RevisionConflict("candidate is already resolved or changed")
    now = datetime.now(timezone.utc)
    if action == "reject":
        for pair in pending:
            pair.status = "rejected"
            pair.decided_at = now
        db.commit()
        return {"status": "rejected"}
    if action != "merge" or len(set(selected_ids)) < 2:
        raise ValueError("merge requires at least two selected items")
    allowed = set(group["member_ids"])
    selected = set(selected_ids)
    if not selected <= allowed:
        raise ValueError("selected items are outside the candidate")
    existing = db.scalars(
        select(ContentFamilyMembership)
        .where(ContentFamilyMembership.item_id.in_(selected))
        .order_by(ContentFamilyMembership.family_id, ContentFamilyMembership.item_id)
        .with_for_update()
    ).all()
    family_ids = {row.family_id for row in existing}
    if family_ids:
        db.scalars(
            select(ContentFamily)
            .where(ContentFamily.id.in_(family_ids))
            .order_by(ContentFamily.id)
            .with_for_update()
        ).all()
    expanded = set(selected)
    if family_ids:
        expanded.update(db.scalars(select(ContentFamilyMembership.item_id).where(ContentFamilyMembership.family_id.in_(family_ids))).all())
    if family_ids:
        family = db.get(ContentFamily, sorted(family_ids, key=str)[0])
    else:
        key = "family-manual-" + hashlib.sha256("|".join(sorted(map(str, expanded))).encode()).hexdigest()[:18]
        family = ContentFamily(family_key=key)
        db.add(family)
        db.flush()
    for membership in db.scalars(select(ContentFamilyMembership).where(ContentFamilyMembership.item_id.in_(expanded))).all():
        membership.family_id = family.id
    existing_item_ids = set(db.scalars(select(ContentFamilyMembership.item_id).where(ContentFamilyMembership.item_id.in_(expanded))).all())
    for item_id in expanded - existing_item_ids:
        db.add(ContentFamilyMembership(item_id=item_id, family_id=family.id))
    for pair in pending:
        endpoints = {pair.left_item_id, pair.right_item_id}
        if endpoints <= expanded:
            pair.status = "merged"
            pair.decided_at = now
        elif endpoints & expanded:
            pair.status = "rejected"
            pair.decided_at = now
    db.commit()
    return {"status": "merged", "family_id": str(family.id), "members": len(expanded)}
