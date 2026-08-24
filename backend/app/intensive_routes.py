from __future__ import annotations

from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models import IntensivePage


router = APIRouter()
DAY_CODES = {"day-1", "day-2", "day-3", "day-4"}
ALLOWED_TAGS = {
    "h1", "h2", "h3", "p", "div", "ul", "ol", "li", "strong", "em",
    "a", "blockquote", "br", "hr",
}
VOID_TAGS = {"br", "hr"}
BLOCKED_TAGS = {"script", "style", "iframe", "object", "svg", "math"}


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


def page_payload(day_code: str, page: IntensivePage | None) -> dict[str, object]:
    return {
        "ok": True,
        "day_code": day_code,
        "html": page.body_html if page else None,
        "version": page.version if page else 0,
        "updated_at": page.updated_at.isoformat() if page else None,
    }


@router.get("/api/intensive/{day_code}")
def public_intensive_page(day_code: str, db: Session = Depends(get_db)) -> dict[str, object]:
    day_code = checked_day(day_code)
    return page_payload(day_code, db.get(IntensivePage, day_code))


@router.get("/admin/api/intensive/{day_code}")
def admin_intensive_page(
    day_code: str,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    day_code = checked_day(day_code)
    return page_payload(day_code, db.get(IntensivePage, day_code))


@router.put("/admin/api/intensive/{day_code}")
def save_intensive_page(
    day_code: str,
    body: IntensivePageUpdate,
    admin_username: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    day_code = checked_day(day_code)
    clean_html = sanitize_article_html(body.html)
    if body.version == 0:
        page = IntensivePage(
            day_code=day_code,
            body_html=clean_html,
            version=1,
            updated_by=admin_username,
        )
        db.add(page)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Страница уже изменена. Обновите её перед сохранением",
            ) from exc
    else:
        result = db.execute(
            update(IntensivePage)
            .where(
                IntensivePage.day_code == day_code,
                IntensivePage.version == body.version,
            )
            .values(
                body_html=clean_html,
                version=body.version + 1,
                updated_by=admin_username,
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Страница уже изменена. Обновите её перед сохранением",
            )
        db.commit()
        page = db.get(IntensivePage, day_code)
    if page is None:
        raise HTTPException(status_code=500, detail="Не удалось сохранить страницу")
    db.refresh(page)
    return page_payload(day_code, page)
