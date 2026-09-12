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

from app.auth import require_admin
from app.database import get_db
from app.models import PublicHomepageEvent


router = APIRouter(tags=["public-homepage-analytics"])
PAGE_ID = "masterclass-homepage-2026"
EVENT_TYPES = {
    "page_open",
    "section_seen",
    "cta_click",
    "popup_open",
    "checkout_open",
    "checkout_started",
    "section_active_10s",
    "section_active_30s",
    "page_active_30s",
    "page_active_90s",
    "page_active_180s",
}
SECTION_IDS = {
    "page_open",
    "hero_video",
    "recognition",
    "approach",
    "before_after",
    "program_inside",
    "experience",
    "free_intensive",
    "reviews_featured",
    "method",
    "pricing",
    "program_days",
    "anya_story",
    "result_21_days",
    "about",
    "faq",
    "final_choice",
    "reviews_more",
    "reviews_wall",
    "program",
    "recipes",
    "consultation",
    "calories",
    "training",
    "contacts",
    "account",
    "checkout",
    "page_time",
    "tariff_basic",
    "tariff_recipes",
    "tariff_consult",
}
RATE_WINDOW_SECONDS = 60
MAX_EVENTS_PER_WINDOW = 80
_rate_lock = Lock()
_rate_state: dict[str, tuple[float, int]] = {}


class PublicHomepageEventIn(BaseModel):
    event: Literal[
        "page_open",
        "section_seen",
        "cta_click",
        "popup_open",
        "checkout_open",
        "checkout_started",
        "section_active_10s",
        "section_active_30s",
        "page_active_30s",
        "page_active_90s",
        "page_active_180s",
    ]
    viewer_id: uuid.UUID
    session_id: uuid.UUID
    page_id: str = Field(min_length=1, max_length=120)
    page_path: str = Field(min_length=1, max_length=255)
    section_id: str = Field(min_length=1, max_length=80)

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
        if value not in SECTION_IDS:
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
) -> dict[str, bool]:
    enforce_rate_limit(request)
    if body.event == "page_open" and body.section_id != "page_open":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "page_open requires page_open section")
    if body.event != "page_open" and body.section_id == "page_open":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "homepage event requires a target")
    row = PublicHomepageEvent(
        session_id=str(body.session_id),
        viewer_key=viewer_key(body.viewer_id),
        page_id=body.page_id,
        page_path=body.page_path,
        event_type=body.event,
        section_id=body.section_id,
    )
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
    return {
        "page_id": PAGE_ID,
        "days": days,
        "sessions": int(counts.get(("page_open", "page_open"), 0)),
        "sections": [
            {"id": section_id, "sessions": int(counts.get(("section_seen", section_id), 0))}
            for section_id in sorted(SECTION_IDS - {"page_open"})
        ],
        "interactions": [
            {
                "event": event_type,
                "target": section_id,
                "sessions": int(count),
            }
            for (event_type, section_id), count in sorted(counts.items())
            if event_type not in {"page_open", "section_seen"}
        ],
    }
