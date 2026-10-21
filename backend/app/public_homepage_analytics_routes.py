from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import Lock
import time
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.auth import require_admin
from app.database import get_db
from app.models import PublicHomepageEvent, TelegramTrackingEvent


router = APIRouter(tags=["public-homepage-analytics"])
PAGE_ID = "masterclass-homepage-2026"
SECTION_IDS = (
    "hero_intro",
    "hero_video",
    "recognition",
    "approach",
    "program_inside",
    "before_after",
    "experience",
    "reviews_featured",
    "method",
    "pricing",
    "program_days",
    "anya_story",
    "about",
    "faq",
    "final_choice",
    "reviews_more",
    "reviews_wall",
    "free_intensive",
)
SECTION_NAMES = dict(zip(SECTION_IDS, (
    "Первый экран", "Видео о подходе", "Знакомые трудности", "Подход", "Что внутри мастер-класса",
    "До и после", "Опыт участников", "Отзывы участников", "Метод и образование", "Тарифы",
    "Программа по дням", "История Ани", "Об авторе", "Вопросы и ответы", "Выбор участия",
    "Дополнительные отзывы", "Стена отзывов", "Бесплатная статья",
)))
CTA_IDS = (
    "pricing_nav_menu",
    "pricing_hero",
    "pricing_anya_story",
    "pricing_final_choice",
    "pricing_after_reviews",
    "pricing_plan_basic",
    "pricing_plan_recipes",
    "pricing_plan_consult",
    "pricing_program_overlay",
)
LEGACY_SECTION_IDS = {"result_21_days"}
LEGACY_CTA_IDS = {"pricing_nav_desktop", "pricing_nav_mobile"}
ALLOWED_SECTION_IDS = {*SECTION_IDS, *LEGACY_SECTION_IDS}
ALLOWED_CTA_IDS = {*CTA_IDS, *LEGACY_CTA_IDS}
ALLOWED_TARGET_IDS = {"page_open", *ALLOWED_SECTION_IDS, *ALLOWED_CTA_IDS}
RATE_WINDOW_SECONDS = 60
MAX_EVENTS_PER_WINDOW = 80
_rate_lock = Lock()
_rate_state: dict[str, tuple[float, int]] = {}


class PublicHomepageEventIn(BaseModel):
    event: Literal["page_open", "section_seen", "cta_click", "scroll_depth"]
    viewer_id: uuid.UUID
    session_id: uuid.UUID
    page_id: str = Field(min_length=1, max_length=120)
    page_path: str = Field(min_length=1, max_length=255)
    section_id: str = Field(min_length=1, max_length=80)
    context: str | None = Field(default=None, max_length=512)
    scroll_percent: int | None = Field(default=None, ge=0, le=100)

    @field_validator("page_id")
    @classmethod
    def validate_page_id(cls, value: str) -> str:
        if value != PAGE_ID:
            raise ValueError("unknown page_id")
        return value

    @field_validator("page_path")
    @classmethod
    def validate_page_path(cls, value: str) -> str:
        if not value.startswith("/") or "\n" in value or "\r" in value:
            raise ValueError("invalid page_path")
        return value

    @field_validator("section_id")
    @classmethod
    def validate_section_id(cls, value: str) -> str:
        if value not in ALLOWED_TARGET_IDS:
            raise ValueError("unknown section_id")
        return value


def viewer_key(viewer_id: uuid.UUID) -> str:
    return sha256(str(viewer_id).encode("ascii")).hexdigest()


def enforce_rate_limit(request: Request) -> None:
    client_key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_lock:
        started_at, events = _rate_state.get(client_key, (now, 0))
        if now - started_at >= RATE_WINDOW_SECONDS:
            started_at, events = now, 0
        if events >= MAX_EVENTS_PER_WINDOW:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "homepage analytics rate limit exceeded")
        _rate_state[client_key] = (started_at, events + 1)


@router.post("/api/public/homepage-analytics")
def collect_public_homepage_event(
    body: PublicHomepageEventIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    enforce_rate_limit(request)
    if body.event == "page_open" and body.section_id != "page_open":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "page_open requires page_open section")
    if body.event == "section_seen" and body.section_id not in ALLOWED_SECTION_IDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "section_seen requires a section")
    if body.event == "cta_click" and body.section_id not in ALLOWED_CTA_IDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "cta_click requires a CTA")
    if body.event == "scroll_depth" and (body.section_id != "page_open" or body.scroll_percent is None):
        raise HTTPException(422, "scroll_depth requires page target and depth")
    row = PublicHomepageEvent(
        session_id=str(body.session_id),
        viewer_key=viewer_key(body.viewer_id),
        page_id=body.page_id,
        page_path=body.page_path,
        event_type=body.event,
        section_id=body.section_id,
    )
    from app.browser_journey_service import COOKIE_NAME, context_id, state_row
    browser_id = context_id(settings.app_auth_secret, body.context or request.cookies.get(COOKIE_NAME))
    browser = state_row(db, browser_id) if browser_id else None
    if browser:
        db.add(TelegramTrackingEvent(id=str(uuid.uuid4()), user_id=browser.user_id,
            event_type="homepage_observation",
            deduplication_key=f"homepage:{body.session_id}:{body.event}:{body.section_id}" + (f":{body.scroll_percent // 5}" if body.event == "scroll_depth" else ""),
            metadata_json={"browser_id": browser.metadata_json["browser_id"],
                "session_id": str(body.session_id), "page_path": body.page_path,
                "action": body.event, "section_id": body.section_id, "scroll_percent": body.scroll_percent},
            occurred_at=datetime.now(timezone.utc)))
    if body.event != "scroll_depth":
        db.add(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        # The unique index intentionally makes repeated observers idempotent.
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return {"ok": True}
        raise
    return {"ok": True}


@router.get("/api/admin/public-homepage-analytics")
def public_homepage_analytics_summary(
    days: int = 30,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    days = max(1, min(days, 366))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(
            PublicHomepageEvent.event_type,
            PublicHomepageEvent.section_id,
            func.count(func.distinct(PublicHomepageEvent.session_id)),
        )
        .where(PublicHomepageEvent.page_id == PAGE_ID, PublicHomepageEvent.created_at >= since)
        .group_by(PublicHomepageEvent.event_type, PublicHomepageEvent.section_id)
    ).all()
    counts = {(event_type, section_id): count for event_type, section_id, count in rows}
    page_paths = db.execute(
        select(PublicHomepageEvent.page_path, func.count(func.distinct(PublicHomepageEvent.session_id)))
        .where(
            PublicHomepageEvent.page_id == PAGE_ID,
            PublicHomepageEvent.event_type == "page_open",
            PublicHomepageEvent.created_at >= since,
        )
        .group_by(PublicHomepageEvent.page_path)
        .order_by(func.count(func.distinct(PublicHomepageEvent.session_id)).desc())
    ).all()
    return {
        "page_id": PAGE_ID,
        "days": days,
        "sessions": int(counts.get(("page_open", "page_open"), 0)),
        "page_paths": [{"path": path, "sessions": int(count)} for path, count in page_paths],
        "sections": [
            {"id": section_id, "sessions": int(counts.get(("section_seen", section_id), 0))}
            for section_id in SECTION_IDS
        ],
        "ctas": [
            {"id": cta_id, "sessions": int(counts.get(("cta_click", cta_id), 0))}
            for cta_id in (*CTA_IDS, *sorted(LEGACY_CTA_IDS))
        ],
    }
