from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ContentImportRun,
    ContentItem,
    ContentItemVersion,
    ContentLink,
    ContentMedia,
    ContentMetricSnapshot,
    ContentSource,
)


PARSER_VERSION = "pikabu-browser-v1"
REFERENCE_DOMAINS = ("pubmed.ncbi.nlm.nih.gov", "doi.org", "jamanetwork.com")


def decode_pikabu_redirect(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname.endswith("pikabu.ru"):
        target = parse_qs(parsed.query).get("u")
        if target:
            return target[0]
    return url


def classify_link(url: str) -> tuple[str, bool]:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname in {"t.me", "telegram.me"}:
        return "telegram", False
    if hostname.endswith("pikabu.ru") and "/story/" in urlparse(url).path:
        return "internal_post", False
    if any(hostname == item or hostname.endswith(f".{item}") for item in REFERENCE_DOMAINS):
        return "reference", True
    return "other", False


def normalized_payload(raw: dict) -> dict:
    external_id = str(raw.get("external_id") or raw.get("story_id") or "").strip()
    canonical_url = str(raw.get("canonical_url") or "").strip()
    title = str(raw.get("title") or "").strip()
    text_content = str(raw.get("text") or raw.get("text_content") or "").strip()
    if not external_id or not canonical_url or not title or not text_content:
        raise ValueError("external_id, canonical_url, title and text are required")
    if f"_{external_id}" not in urlparse(canonical_url).path:
        raise ValueError("canonical_url does not match external_id")

    links = []
    for position, item in enumerate(raw.get("links") or []):
        wrapped = str(item.get("wrapped_url") or item.get("wrapped") or item.get("url") or "")
        if not wrapped:
            continue
        target = decode_pikabu_redirect(str(item.get("target_url") or item.get("final") or wrapped))
        link_type, ignored = classify_link(target)
        links.append(
            {
                "visible_text": str(item.get("text") or "").strip() or None,
                "wrapped_url": wrapped,
                "target_url": target,
                "domain": (urlparse(target).hostname or "").lower() or None,
                "link_type": link_type,
                "is_cta": bool(item.get("is_cta")),
                "ignored_for_generation": ignored,
                "position": position,
            }
        )

    media = []
    for position, item in enumerate(raw.get("media") or []):
        source_url = str(item.get("source_url") or item.get("url") or "").strip()
        if not source_url:
            continue
        media.append(
            {
                "media_type": str(item.get("media_type") or item.get("type") or "other"),
                "source_url": source_url,
                "preview_url": item.get("preview_url"),
                "position": position,
                "metadata_json": item.get("metadata") or {},
            }
        )

    blocks = raw.get("blocks") or []
    published_at = raw.get("published_at")
    if isinstance(published_at, str) and published_at:
        published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    else:
        published_at = None
    ending_text = str(raw.get("ending_text") or "").strip() or None
    cta_url = str(raw.get("cta_url") or "").strip() or None
    if cta_url:
        cta_url = decode_pikabu_redirect(cta_url)
        for link in links:
            if link["target_url"] == cta_url:
                link["is_cta"] = True
    result = {
        "external_id": external_id,
        "canonical_url": canonical_url,
        "title": title,
        "author_name": raw.get("author_name") or "armagedongt",
        "published_at": published_at,
        "status": raw.get("status") or "published",
        "source_tags": raw.get("tags") or [],
        "text_content": text_content,
        "blocks": blocks,
        "ending_text": ending_text,
        "ending_kind": raw.get("ending_kind"),
        "cta_text": raw.get("cta_text"),
        "cta_url": cta_url,
        "recommendations_status": raw.get("recommendations_status") or "review",
        "links": links,
        "media": media,
        "metrics": raw.get("metrics") or {},
    }
    hash_body = json.dumps(
        {
            "title": title,
            "text": text_content,
            "blocks": blocks,
            "links": links,
            "media": media,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    result["content_hash"] = hashlib.sha256(hash_body.encode("utf-8")).hexdigest()
    return result


def get_or_create_pikabu_source(db: Session) -> ContentSource:
    source = db.scalar(
        select(ContentSource).where(
            ContentSource.platform == "pikabu", ContentSource.account_key == "armagedongt"
        )
    )
    if source:
        return source
    source = ContentSource(
        platform="pikabu",
        account_key="armagedongt",
        display_name="armagedongt",
        canonical_url="https://pikabu.ru/@armagedongt",
    )
    db.add(source)
    db.flush()
    return source


def import_pikabu_items(db: Session, rows: list[dict], *, mode: str = "manual_json") -> dict:
    source = get_or_create_pikabu_source(db)
    run = ContentImportRun(
        source_id=source.id, mode=mode, status="running", parser_version=PARSER_VERSION
    )
    db.add(run)
    db.flush()
    summary = {"discovered": len(rows), "created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    errors: list[dict] = []

    for raw in rows:
        try:
            data = normalized_payload(raw)
            item = db.scalar(
                select(ContentItem).where(
                    ContentItem.source_id == source.id,
                    ContentItem.external_id == data["external_id"],
                )
            )
            created = item is None
            if item is None:
                item = ContentItem(
                    source_id=source.id,
                    external_id=data["external_id"],
                    canonical_url=data["canonical_url"],
                    title=data["title"],
                )
                db.add(item)
                db.flush()
            item.canonical_url = data["canonical_url"]
            item.title = data["title"]
            item.author_name = data["author_name"]
            item.published_at = data["published_at"]
            item.status = data["status"]
            item.source_tags = data["source_tags"]
            item.ending_text = data["ending_text"]
            item.ending_kind = data["ending_kind"]
            item.cta_text = data["cta_text"]
            item.cta_url = data["cta_url"]
            item.recommendations_status = data["recommendations_status"]

            version = db.scalar(
                select(ContentItemVersion).where(
                    ContentItemVersion.item_id == item.id,
                    ContentItemVersion.content_hash == data["content_hash"],
                )
            )
            if version is None:
                next_no = (db.scalar(select(func.max(ContentItemVersion.version_no)).where(ContentItemVersion.item_id == item.id)) or 0) + 1
                version = ContentItemVersion(
                    item_id=item.id,
                    version_no=next_no,
                    content_hash=data["content_hash"],
                    text_content=data["text_content"],
                    blocks=data["blocks"],
                    parser_version=PARSER_VERSION,
                )
                db.add(version)
                db.flush()
                for media in data["media"]:
                    db.add(ContentMedia(item_id=item.id, version_id=version.id, **media))
                for link in data["links"]:
                    db.add(ContentLink(item_id=item.id, version_id=version.id, **link))
                item.latest_version_id = version.id
                summary["created" if created else "updated"] += 1
            else:
                item.latest_version_id = version.id
                summary["unchanged"] += 1

            metrics = data["metrics"]
            if metrics:
                db.add(
                    ContentMetricSnapshot(
                        item_id=item.id,
                        metric_source="pikabu_page",
                        views=metrics.get("views"),
                        rating=metrics.get("rating"),
                        pluses=metrics.get("pluses"),
                        minuses=metrics.get("minuses"),
                        saves=metrics.get("saves"),
                        comments_reported=metrics.get("comments_reported"),
                        emotions=metrics.get("emotions") or [],
                    )
                )
        except (TypeError, ValueError) as exc:
            summary["failed"] += 1
            errors.append({"external_id": raw.get("external_id"), "error": str(exc)})

    source.last_synced_at = datetime.now(timezone.utc)
    run.status = "partial" if summary["failed"] else "completed"
    run.finished_at = datetime.now(timezone.utc)
    run.summary = {**summary, "errors": errors}
    db.commit()
    return run.summary


def content_summary(db: Session) -> dict:
    items = db.scalar(select(func.count(ContentItem.id))) or 0
    sources = db.scalar(select(func.count(ContentSource.id))) or 0
    return {"items": items, "sources": sources}


def list_content_items(db: Session, *, q: str = "", source: str = "", limit: int = 100, offset: int = 0) -> list[dict]:
    statement = select(ContentItem, ContentSource).join(ContentSource, ContentSource.id == ContentItem.source_id)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(or_(ContentItem.title.ilike(pattern), ContentItem.external_id.ilike(pattern)))
    if source:
        statement = statement.where(ContentSource.platform == source)
    rows = db.execute(statement.order_by(ContentItem.published_at.desc().nullslast()).offset(offset).limit(limit)).all()
    result = []
    for item, src in rows:
        metric = db.scalar(
            select(ContentMetricSnapshot)
            .where(ContentMetricSnapshot.item_id == item.id)
            .order_by(ContentMetricSnapshot.captured_at.desc())
            .limit(1)
        )
        result.append({
            "id": str(item.id), "source": src.platform, "external_id": item.external_id,
            "title": item.title, "canonical_url": item.canonical_url,
            "published_at": item.published_at, "status": item.status,
            "ending_text": item.ending_text, "cta_url": item.cta_url,
            "recommendations_status": item.recommendations_status,
            "views": metric.views if metric else None, "rating": metric.rating if metric else None,
            "saves": metric.saves if metric else None,
        })
    return result


def get_content_item(db: Session, item_id: uuid.UUID) -> dict | None:
    item = db.get(ContentItem, item_id)
    if not item:
        return None
    source = db.get(ContentSource, item.source_id)
    version = db.get(ContentItemVersion, item.latest_version_id) if item.latest_version_id else None
    links = db.scalars(select(ContentLink).where(ContentLink.version_id == item.latest_version_id).order_by(ContentLink.position)).all() if version else []
    media = db.scalars(select(ContentMedia).where(ContentMedia.version_id == item.latest_version_id).order_by(ContentMedia.position)).all() if version else []
    return {
        "id": str(item.id), "source": source.platform if source else None,
        "external_id": item.external_id, "canonical_url": item.canonical_url,
        "title": item.title, "published_at": item.published_at, "tags": item.source_tags,
        "text": version.text_content if version else None, "blocks": version.blocks if version else [],
        "ending_text": item.ending_text, "ending_kind": item.ending_kind,
        "cta_text": item.cta_text, "cta_url": item.cta_url,
        "recommendations_status": item.recommendations_status,
        "links": [{"text": x.visible_text, "url": x.target_url, "type": x.link_type, "ignored_for_generation": x.ignored_for_generation} for x in links],
        "media": [{"type": x.media_type, "source_url": x.source_url, "preview_url": x.preview_url, "position": x.position} for x in media],
    }
