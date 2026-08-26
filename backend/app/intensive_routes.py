from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.article_markup import sanitize_article_html
from app.database import get_db
from app.models import ContentItem, ContentItemVersion, ContentSource


router = APIRouter()
DAY_CODES = {"day-1", "day-2", "day-3", "day-4"}
SOURCE_PLATFORM = "internal"
SOURCE_ACCOUNT_KEY = "free-intensive"
DAY_TITLES = {
    "day-1": "День 1. Сначала увидьте своё питание",
    "day-2": "День 2. Сделайте дефицит легче",
    "day-3": "День 3. Калории и реальность похудения",
    "day-4": "День 4. Полная карта похудения",
}


class IntensivePageUpdate(BaseModel):
    html: str = Field(min_length=1, max_length=250_000)
    version: int = Field(ge=0)


def intensive_version_hash(day_code: str, version_no: int, html: str) -> str:
    payload = f"{day_code}\0{version_no}\0{html}"
    return hashlib.sha256(payload.encode()).hexdigest()


def checked_day(day_code: str) -> str:
    if day_code not in DAY_CODES:
        raise HTTPException(status_code=404, detail="intensive day not found")
    return day_code


def intensive_item(db: Session, day_code: str) -> ContentItem | None:
    return db.scalar(
        select(ContentItem)
        .join(ContentSource, ContentSource.id == ContentItem.source_id)
        .where(
            ContentSource.platform == SOURCE_PLATFORM,
            ContentSource.account_key == SOURCE_ACCOUNT_KEY,
            ContentItem.external_id == day_code,
        )
    )


def latest_version(db: Session, item: ContentItem | None) -> ContentItemVersion | None:
    if item is None or item.latest_version_id is None:
        return None
    return db.get(ContentItemVersion, item.latest_version_id)


def page_payload(day_code: str, version: ContentItemVersion | None) -> dict[str, object]:
    return {
        "ok": True,
        "day_code": day_code,
        "html": version.text_content if version else None,
        "version": version.version_no if version else 0,
        "updated_at": version.imported_at.isoformat() if version else None,
    }


@router.get("/api/intensive/{day_code}")
def public_intensive_page(day_code: str, db: Session = Depends(get_db)) -> dict[str, object]:
    day_code = checked_day(day_code)
    return page_payload(day_code, latest_version(db, intensive_item(db, day_code)))


@router.get("/admin/api/intensive/{day_code}")
def admin_intensive_page(
    day_code: str,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    day_code = checked_day(day_code)
    return page_payload(day_code, latest_version(db, intensive_item(db, day_code)))


@router.put("/admin/api/intensive/{day_code}")
def save_intensive_page(
    day_code: str,
    body: IntensivePageUpdate,
    admin_username: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    day_code = checked_day(day_code)
    clean_html = sanitize_article_html(body.html)
    item = intensive_item(db, day_code)
    current = latest_version(db, item)
    current_version = current.version_no if current else 0
    if body.version != current_version:
        raise HTTPException(
            status_code=409,
            detail="Страница уже изменена. Обновите её перед сохранением",
        )
    if current and current.text_content == clean_html:
        return page_payload(day_code, current)

    try:
        if item is None:
            source = db.scalar(
                select(ContentSource).where(
                    ContentSource.platform == SOURCE_PLATFORM,
                    ContentSource.account_key == SOURCE_ACCOUNT_KEY,
                )
            )
            if source is None:
                source = ContentSource(
                    platform=SOURCE_PLATFORM,
                    account_key=SOURCE_ACCOUNT_KEY,
                    display_name="Бесплатный интенсив «Последнее похудение»",
                    canonical_url="https://app.edabalans.ru/intensive/day-1",
                )
                db.add(source)
                db.flush()
            item = ContentItem(
                source_id=source.id,
                external_id=day_code,
                canonical_url=f"https://app.edabalans.ru/intensive/{day_code}",
                title=DAY_TITLES[day_code],
                author_name=admin_username,
                status="published",
                source_tags=["free-intensive"],
            )
            db.add(item)
            db.flush()

        version = ContentItemVersion(
            item_id=item.id,
            version_no=current_version + 1,
            content_hash=intensive_version_hash(day_code, current_version + 1, clean_html),
            text_content=clean_html,
            blocks=[],
            parser_version="intensive-editor-v2",
        )
        db.add(version)
        db.flush()
        item.latest_version_id = version.id
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Страница уже изменена. Обновите её перед сохранением",
        ) from exc
    db.refresh(version)
    return page_payload(day_code, version)
