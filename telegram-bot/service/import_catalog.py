from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path

import httpx
from sqlalchemy import select

from app.database import SessionLocal
from app.formatting import to_telegram_html
from app.models import ContentItem, Sequence, SequenceStep, SequenceVersion


CURATED_SEQUENCE_POSTS = {
    "m13": "0ae26308b28517cdbf8094a8",  # Главный принцип: добавляй, а не исключай
    "m14": "1483db614a884fb728f8f104",  # Плохой план похудения
    "m15": "4dfd5964b650de3f64955293",  # Вы не обязаны худеть
    "m16": "12190fdeac2867f163e03ab2",  # Осознанность о количестве сладкого
}


def safe_name(item_id: str, original: str | None, url: str) -> str:
    suffix = Path(original or url.split("?", 1)[0]).suffix.lower() or ".bin"
    return f"{hashlib.sha256(item_id.encode()).hexdigest()[:16]}{suffix}"


def run(source: Path, media_dir: Path | None = None, container_media_root: str = "/app/media") -> dict[str, int]:
    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    media_rows = connection.execute("SELECT * FROM archive_media_assets ORDER BY id").fetchall()
    by_item: dict[str, sqlite3.Row] = {}
    for row in media_rows:
        by_item.setdefault(row["archive_content_item_id"], row)
    imported = downloaded = linked = 0
    with SessionLocal() as session:
        for row in connection.execute("SELECT * FROM archive_content_items ORDER BY scenario_name, id"):
            code = f"leadteh_{row['id']}"
            item = session.scalar(select(ContentItem).where(ContentItem.code == code))
            media = by_item.get(row["id"])
            media_path = None
            if media:
                media_path = media["source_url"]
                if media_dir:
                    media_dir.mkdir(parents=True, exist_ok=True)
                    filename = safe_name(row["id"], media["filename"], media["source_url"])
                    destination = media_dir / filename
                    if not destination.exists():
                        with httpx.stream("GET", media["source_url"], follow_redirects=True, timeout=120) as response:
                            response.raise_for_status()
                            with destination.open("wb") as stream:
                                for chunk in response.iter_bytes():
                                    stream.write(chunk)
                        downloaded += 1
                    media_path = f"{container_media_root.rstrip('/')}/{filename}"
            values = dict(
                title=row["title"], body_source=to_telegram_html(row["source_text"]),
                source_format="telegram_html", media_kind=row["media_kind"], media_path=media_path,
                labels=[x for x in [row["classification"], row["scenario_name"]] if x], status="archive_copy",
                origin_system=row["source_system"], origin_scenario_id=row["source_scenario_id"],
                origin_scenario_name=row["scenario_name"], origin_block_id=row["source_block_id"],
            )
            if item:
                if item.media_path and item.media_path.startswith("/app/media/"):
                    values["media_path"] = item.media_path
                for key, value in values.items(): setattr(item, key, value)
            else:
                session.add(ContentItem(code=code, **values)); imported += 1
        session.flush()
        sequence = session.scalar(select(Sequence).where(Sequence.code == "prepurchase_masterclass"))
        if sequence:
            version = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == sequence.id).order_by(SequenceVersion.version_no.desc()))
            for step_key, archive_id in CURATED_SEQUENCE_POSTS.items():
                step = session.scalar(select(SequenceStep).where(SequenceStep.sequence_version_id == version.id, SequenceStep.step_key == step_key))
                item = session.scalar(select(ContentItem).where(ContentItem.code == f"leadteh_{archive_id}"))
                if step and item and step.content_item_id != item.id:
                    step.content_item_id = item.id; step.label = item.title; linked += 1
        session.commit()
    return {"archive_items": connection.execute("SELECT count(*) FROM archive_content_items").fetchone()[0], "inserted": imported, "media_downloaded": downloaded, "curated_linked": linked}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--media-dir", type=Path)
    parser.add_argument("--container-media-root", default="/app/media")
    args = parser.parse_args()
    print(run(args.source, args.media_dir, args.container_media_root))
