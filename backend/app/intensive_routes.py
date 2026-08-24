from __future__ import annotations

import hashlib
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models import ContentItem, ContentItemVersion, ContentSource


router = APIRouter()
DAY_CODES = {"day-1", "day-2", "day-3", "day-4"}
ALLOWED_TAGS = {
    "h1", "h2", "h3", "p", "div", "ul", "ol", "li", "strong", "em",
    "a", "blockquote", "br", "hr",
}
VOID_TAGS = {"br", "hr"}
BLOCKED_TAGS = {"script", "style", "iframe", "object", "svg", "math"}
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


class ArticleSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in BLOCKED_TAGS:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in ALLOWED_TAGS:
            return
        rendered_attrs = ""
        if tag == "a":
            href = next((value for name, value in attrs if name.lower() == "href"), None)
            if href and safe_href(href):
                rendered_attrs = f' href="{escape(href, quote=True)}"'
        self.parts.append(f"<{tag}{rendered_attrs}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in BLOCKED_TAGS or self.blocked_depth:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in BLOCKED_TAGS:
            self.blocked_depth = max(0, self.blocked_depth - 1)
            return
        if not self.blocked_depth and tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.parts.append(escape(data))


def safe_href(value: str) -> bool:
    cleaned = value.strip()
    if cleaned.startswith("//") or any(ord(character) < 32 for character in cleaned):
        return False
    return urlparse(cleaned).scheme in {"", "http", "https", "mailto"}


def sanitize_article_html(value: str) -> str:
    parser = ArticleSanitizer()
    parser.feed(value)
    parser.close()
    result = "".join(parser.parts).strip()
    if not result:
        raise HTTPException(status_code=422, detail="Текст страницы не может быть пустым")
    return result


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
            content_hash=hashlib.sha256(clean_html.encode()).hexdigest(),
            text_content=clean_html,
            blocks=[],
            parser_version="intensive-editor-v1",
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
