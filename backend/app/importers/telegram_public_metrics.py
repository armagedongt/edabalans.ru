from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ContentItem, ContentItemVersion, ContentMetricSnapshot, ContentSource


def import_metrics(payload: dict, *, apply: bool) -> dict:
    rows = payload.get("items") or []
    channel = str((payload.get("source") or {}).get("channel") or "").strip().lstrip("@")
    if not channel:
        raise ValueError("source.channel is required")
    with SessionLocal() as db:
        source = db.scalar(
            select(ContentSource).where(
                ContentSource.platform == "telegram",
                ContentSource.canonical_url.in_([f"https://t.me/{channel}", f"https://telegram.me/{channel}"]),
            )
        )
        if not source:
            raise ValueError(f"Telegram content source @{channel} not found")
        items = db.scalars(select(ContentItem).where(ContentItem.source_id == source.id)).all()
        by_message: dict[int, ContentItem] = {}
        for item in items:
            version = db.get(ContentItemVersion, item.latest_version_id) if item.latest_version_id else None
            for block in version.blocks if version else []:
                message_id = block.get("message_id")
                if isinstance(message_id, int):
                    by_message[message_id] = item

        grouped: dict[object, list[dict]] = defaultdict(list)
        unmatched = 0
        for row in rows:
            item = by_message.get(int(row.get("message_id") or 0))
            if item:
                grouped[item.id].append(row)
            else:
                unmatched += 1

        created = 0
        unchanged = 0
        for item_id, group in grouped.items():
            views = max((row.get("views") for row in group if row.get("views") is not None), default=None)
            reaction_totals: dict[str, int] = defaultdict(int)
            for row in group:
                for reaction in row.get("reactions") or []:
                    reaction_totals[str(reaction.get("emoji") or "")] += int(reaction.get("count") or 0)
            emotions = [
                {"type": "emoji", "emoji": emoji, "count": count}
                for emoji, count in sorted(reaction_totals.items()) if emoji
            ]
            details = {"message_ids": sorted(int(row["message_id"]) for row in group)}
            previous = db.scalar(
                select(ContentMetricSnapshot)
                .where(
                    ContentMetricSnapshot.item_id == item_id,
                    ContentMetricSnapshot.metric_source == "telegram_public",
                )
                .order_by(ContentMetricSnapshot.captured_at.desc())
                .limit(1)
            )
            if previous and previous.views == views and previous.emotions == emotions and previous.details_json == details:
                unchanged += 1
                continue
            created += 1
            if apply:
                db.add(
                    ContentMetricSnapshot(
                        item_id=item_id,
                        metric_source="telegram_public",
                        views=views,
                        emotions=emotions,
                        details_json=details,
                    )
                )
        if apply:
            db.commit()
        else:
            db.rollback()
        return {
            "messages": len(rows), "matched_items": len(grouped), "unmatched_messages": unmatched,
            "snapshots_created": created, "unchanged": unchanged, "applied": apply,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import public Telegram metric snapshots")
    parser.add_argument("path", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.backup_confirmed:
        raise SystemExit("--apply requires --backup-confirmed")
    payload = json.loads(args.path.read_text(encoding="utf-8"))
    print(json.dumps(import_metrics(payload, apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
