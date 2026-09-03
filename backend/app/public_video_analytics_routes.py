from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from threading import Lock
import time
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PublicVideoView


router = APIRouter(tags=["public-video-analytics"])
ALLOWED_VIDEO_IDS = {
    "homepage-vsl-2026-02-13",
    "homepage-vsl-2026-09-02",
    "homepage-anya-review-2026-09-01",
    "intensive-day-1-2026-09-03",
}
MAX_VIDEO_SECONDS = 7_200
BUCKET_SIZE_SECONDS = 5
RATE_WINDOW_SECONDS = 60
MAX_EVENTS_PER_WINDOW = 240
MAX_ENGAGEMENTS_PER_WINDOW = 30
_rate_lock = Lock()
_rate_state: dict[str, tuple[float, int, int]] = {}


class PublicVideoAnalyticsIn(BaseModel):
    event: Literal[
        "video_engaged",
        "video_progress",
        "video_complete",
        "video_exit",
    ]
    viewer_id: uuid.UUID
    session_id: uuid.UUID
    video_id: str = Field(min_length=1, max_length=120)
    page_path: str = Field(min_length=1, max_length=255)
    last_position_sec: int = Field(ge=0, le=MAX_VIDEO_SECONDS)
    max_position_sec: int = Field(ge=0, le=MAX_VIDEO_SECONDS)
    watched_buckets_5s: list[int] = Field(default_factory=list, max_length=1_441)

    @field_validator("video_id")
    @classmethod
    def validate_video_id(cls, value: str) -> str:
        if value not in ALLOWED_VIDEO_IDS:
            raise ValueError("unknown video_id")
        return value

    @field_validator("page_path")
    @classmethod
    def validate_page_path(cls, value: str) -> str:
        if not value.startswith("/") or "\n" in value or "\r" in value:
            raise ValueError("invalid page_path")
        return value

    @field_validator("watched_buckets_5s")
    @classmethod
    def validate_watched_buckets(cls, values: list[int]) -> list[int]:
        normalized = sorted(set(values))
        if any(
            value < 0
            or value > MAX_VIDEO_SECONDS
            or value % BUCKET_SIZE_SECONDS != 0
            for value in normalized
        ):
            raise ValueError("invalid watched bucket")
        return normalized


def viewer_key(viewer_id: uuid.UUID) -> str:
    return sha256(str(viewer_id).encode("ascii")).hexdigest()


def enforce_rate_limit(request: Request, *, engagement: bool) -> None:
    client_key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_lock:
        started_at, events, engagements = _rate_state.get(
            client_key, (now, 0, 0)
        )
        if now - started_at >= RATE_WINDOW_SECONDS:
            started_at, events, engagements = now, 0, 0
        if events >= MAX_EVENTS_PER_WINDOW or (
            engagement and engagements >= MAX_ENGAGEMENTS_PER_WINDOW
        ):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "video analytics rate limit exceeded",
            )
        _rate_state[client_key] = (
            started_at,
            events + 1,
            engagements + int(engagement),
        )
        if len(_rate_state) > 5_000:
            expired = [
                key
                for key, (window_start, _, _) in _rate_state.items()
                if now - window_start >= RATE_WINDOW_SECONDS
            ]
            for key in expired:
                _rate_state.pop(key, None)
            if len(_rate_state) > 5_000:
                oldest = sorted(
                    _rate_state,
                    key=lambda key: _rate_state[key][0],
                )[: len(_rate_state) - 4_500]
                for key in oldest:
                    _rate_state.pop(key, None)


@router.post("/api/public/video-analytics")
def collect_public_video_analytics(
    body: PublicVideoAnalyticsIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    enforce_rate_limit(request, engagement=body.event == "video_engaged")
    now = datetime.now(timezone.utc)
    session_id = str(body.session_id)
    hashed_viewer = viewer_key(body.viewer_id)
    row = db.scalar(
        select(PublicVideoView)
        .where(PublicVideoView.session_id == session_id)
        .with_for_update()
    )

    if row is None:
        if body.event != "video_engaged":
            raise HTTPException(409, "video session is not engaged")
        row = PublicVideoView(
            session_id=session_id,
            viewer_key=hashed_viewer,
            video_id=body.video_id,
            page_path=body.page_path,
            status="engaged",
            last_event_type=body.event,
            last_position_sec=body.last_position_sec,
            max_position_sec=max(body.last_position_sec, body.max_position_sec),
            watched_buckets=body.watched_buckets_5s,
            event_count=1,
            completed=body.event == "video_complete",
            engaged_at=now,
            last_event_at=now,
            completed_at=now if body.event == "video_complete" else None,
            exited_at=now if body.event == "video_exit" else None,
        )
        if body.event == "video_exit":
            row.status = "exited"
        elif body.event == "video_complete":
            row.status = "completed"
        db.add(row)
    else:
        if row.viewer_key != hashed_viewer or row.video_id != body.video_id:
            raise HTTPException(409, "session identity mismatch")
        row.page_path = body.page_path
        row.last_event_type = body.event
        row.last_position_sec = body.last_position_sec
        row.max_position_sec = max(
            row.max_position_sec,
            body.max_position_sec,
            body.last_position_sec,
        )
        row.watched_buckets = sorted(
            set(row.watched_buckets or []).union(body.watched_buckets_5s)
        )
        row.event_count += 1
        row.last_event_at = now
        if body.event == "video_complete":
            row.completed = True
            row.completed_at = row.completed_at or now
            row.status = "completed"
        elif body.event == "video_exit" and not row.completed:
            row.exited_at = now
            row.status = "exited"
        elif not row.completed:
            row.status = "watching"

    db.commit()
    return {"ok": True}
