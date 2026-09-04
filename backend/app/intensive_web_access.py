from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    AttributionEvent,
    CourseEvent,
    CourseStageProgress,
    MessengerLinkToken,
    User,
    UserOffer,
)


COURSE_CODE = "intensive"
ACCESS_PURPOSE = "intensive_access"
SESSION_COOKIE = "edabalans_intensive_session"
SESSION_MAX_AGE = 2 * 365 * 24 * 60 * 60
ACCESS_TOKEN_TTL = timedelta(days=2 * 365)
DAY_DELAY = timedelta(hours=23)
OFFER_DURATION = timedelta(hours=72)
OFFER_STAGE_CODE = "intensive_day4_discount"
OFFER_CODE = "intensive-day4-1000"
OFFER_DISCOUNT = 1000
OFFER_TOKEN_PURPOSE = "intensive_offer"
PLATFORMS = {"telegram", "max"}
CLIENT_EVENT_TYPES = {
    "intensive_home_open",
    "intensive_menu_open",
    "intensive_telegram_click",
    "intensive_max_click",
    "intensive_next_day_unlocked",
    "intensive_next_day_click",
    "intensive_masterclass_click",
    "video_engaged",
    "video_progress",
    "video_complete",
    "video_exit",
}
ATTRIBUTION_KEYS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "yclid",
    "alias",
)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _encode(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(value: str) -> dict[str, Any]:
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def _signature(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _signed_value(secret: str, payload: dict[str, Any]) -> str:
    encoded = _encode(payload)
    return f"{encoded}.{_signature(secret, encoded)}"


def _verified_payload(secret: str, value: str | None) -> dict[str, Any] | None:
    if not secret or not value or "." not in value:
        return None
    encoded, supplied = value.rsplit(".", 1)
    if not hmac.compare_digest(supplied, _signature(secret, encoded)):
        return None
    try:
        payload = _decode(encoded)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    expires_at = int(payload.get("exp") or 0)
    if expires_at <= int(time.time()):
        return None
    return payload


def issue_access_token(
    db: Session,
    user_id: uuid.UUID,
    platform: str,
    *,
    now: datetime | None = None,
) -> tuple[str, MessengerLinkToken]:
    if platform not in PLATFORMS:
        raise ValueError("unsupported intensive platform")
    if db.get(User, user_id) is None:
        raise ValueError("intensive user not found")
    current = aware_utc(now or datetime.now(timezone.utc))
    token = "E" + secrets.token_urlsafe(18)
    row = MessengerLinkToken(
        user_id=user_id,
        platform=platform,
        purpose=ACCESS_PURPOSE,
        token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
        expires_at=current + ACCESS_TOKEN_TTL,
    )
    db.add(row)
    db.flush()
    return token, row


def access_token_row(
    db: Session, token: str, *, now: datetime | None = None
) -> MessengerLinkToken | None:
    if not token or len(token) > 128:
        return None
    row = db.scalar(
        select(MessengerLinkToken).where(
            MessengerLinkToken.token_hash
            == hashlib.sha256(token.encode("utf-8")).hexdigest(),
            MessengerLinkToken.purpose == ACCESS_PURPOSE,
        )
    )
    if row is None or row.platform not in PLATFORMS or row.consumed_at is not None:
        return None
    current = aware_utc(now or datetime.now(timezone.utc))
    return row if aware_utc(row.expires_at) > current else None


def consume_access_token(
    db: Session, token: str, *, now: datetime | None = None
) -> MessengerLinkToken | None:
    """Atomically exchange a valid bearer token for a web session."""
    if not token or len(token) > 128:
        return None
    current = aware_utc(now or datetime.now(timezone.utc))
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return db.scalar(
        update(MessengerLinkToken)
        .where(
            MessengerLinkToken.token_hash == digest,
            MessengerLinkToken.purpose == ACCESS_PURPOSE,
            MessengerLinkToken.platform.in_(PLATFORMS),
            MessengerLinkToken.consumed_at.is_(None),
            MessengerLinkToken.expires_at > current,
        )
        .values(consumed_at=current)
        .returning(MessengerLinkToken)
    )


def session_identity(
    request: Request, secret: str
) -> tuple[uuid.UUID, str] | None:
    payload = _verified_payload(secret, request.cookies.get(SESSION_COOKIE))
    if payload is None or payload.get("platform") not in PLATFORMS:
        return None
    try:
        return uuid.UUID(str(payload["user_id"])), str(payload["platform"])
    except (KeyError, ValueError, TypeError):
        return None


def set_session(
    response: Response,
    request: Request,
    secret: str,
    user_id: uuid.UUID,
    platform: str,
) -> None:
    if not secret or platform not in PLATFORMS:
        return
    value = _signed_value(
        secret,
        {
            "user_id": str(user_id),
            "platform": platform,
            "exp": int(time.time()) + SESSION_MAX_AGE,
        },
    )
    response.set_cookie(
        SESSION_COOKIE,
        value,
        max_age=SESSION_MAX_AGE,
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
        path="/",
    )


def clean_entry_url(request: Request) -> str:
    query = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key not in {"i", "token"}
    ]
    parts = urlsplit(str(request.url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def record_entry_attribution(
    db: Session,
    user_id: uuid.UUID,
    platform: str,
    request: Request,
    *,
    now: datetime | None = None,
) -> AttributionEvent:
    current = aware_utc(now or datetime.now(timezone.utc))
    query = request.query_params
    event = AttributionEvent(
        user_id=user_id,
        event_type="intensive_personal_link_open",
        source_raw=platform,
        utm_source=query.get("utm_source"),
        utm_medium=query.get("utm_medium"),
        utm_campaign=query.get("utm_campaign"),
        utm_content=query.get("utm_content"),
        utm_term=query.get("utm_term"),
        ref_code=query.get("yclid") or query.get("alias"),
        landing_url=clean_entry_url(request),
        occurred_at=current,
    )
    db.add(event)
    return event


def course_event(
    db: Session,
    user_id: uuid.UUID,
    event_key: str,
    event_type: str,
    *,
    details: dict[str, Any] | None = None,
) -> CourseEvent:
    event = db.scalar(
        select(CourseEvent).where(
            CourseEvent.user_id == user_id,
            CourseEvent.course_code == COURSE_CODE,
            CourseEvent.event_key == event_key,
        )
    )
    if event is None:
        event = CourseEvent(
            user_id=user_id,
            course_code=COURSE_CODE,
            event_key=event_key,
            event_type=event_type,
            details=details or {},
        )
        db.add(event)
        db.flush()
    return event


def record_client_event(
    db: Session,
    user_id: uuid.UUID,
    platform: str,
    event_type: str,
    event_id: str,
    details: dict[str, Any],
) -> CourseEvent:
    if platform not in PLATFORMS or event_type not in CLIENT_EVENT_TYPES:
        raise ValueError("unsupported intensive event")
    if not event_id or len(event_id) > 100:
        raise ValueError("invalid intensive event id")

    def integer_detail(name: str) -> int:
        value = details.get(name)
        if value in (None, ""):
            return 0
        number = float(value)
        if not math.isfinite(number) or not number.is_integer():
            raise ValueError(f"invalid intensive {name}")
        return int(number)

    rows = progress_rows(db, user_id)
    day = integer_detail("day")
    next_day = integer_detail("next_day")
    if day and day not in range(1, 5):
        raise ValueError("invalid intensive day")
    if event_type.startswith("video_"):
        if day not in rows:
            raise ValueError("intensive day is not open")
        video_id = str(details.get("video_id") or "")[:120]
        if not video_id:
            raise ValueError("video id is required")
        progress = integer_detail("progress_percent")
        if progress not in range(0, 101):
            raise ValueError("invalid intensive video progress")
        suffix = f":{progress}" if event_type == "video_progress" else ""
        event_key = f"video:{video_id}:{event_type}{suffix}"
    elif event_type in {"intensive_next_day_unlocked", "intensive_next_day_click"}:
        if next_day not in range(2, 5) or not day_unlocked(rows, next_day):
            raise ValueError("next intensive day is not open")
        event_key = f"day:{next_day}:{event_type}"
    elif event_type in {"intensive_telegram_click", "intensive_max_click"}:
        clicked_platform = event_type.removeprefix("intensive_").removesuffix("_click")
        if clicked_platform != platform or day not in rows:
            raise ValueError("intensive messenger does not match personal link")
        event_key = f"day:{day}:messenger:{platform}:clicked"
    elif event_type == "intensive_masterclass_click":
        if day and day not in rows:
            raise ValueError("intensive day is not open")
        event_key = f"masterclass:clicked:{day or 'menu'}"
    else:
        event_key = f"web:{event_type}"

    safe_details: dict[str, Any] = {
        "client_event_id": event_id,
        "platform": platform,
    }
    for key in (
        "day",
        "next_day",
        "video_id",
        "progress_percent",
        "position_seconds",
        "duration_seconds",
        "offer_id",
    ):
        value = details.get(key)
        if isinstance(value, (str, int, float, bool)):
            safe_details[key] = value[:200] if isinstance(value, str) else value
    return course_event(
        db,
        user_id,
        event_key,
        event_type,
        details=safe_details,
    )


def progress_rows(db: Session, user_id: uuid.UUID) -> dict[int, CourseStageProgress]:
    return {
        row.stage_number: row
        for row in db.scalars(
            select(CourseStageProgress).where(
                CourseStageProgress.user_id == user_id,
                CourseStageProgress.course_code == COURSE_CODE,
            )
        )
    }


def day_unlocked(
    rows: dict[int, CourseStageProgress], day: int, *, now: datetime | None = None
) -> bool:
    if day == 1:
        return True
    previous = rows.get(day - 1)
    if previous is None or previous.task_opened_at is None:
        return False
    current = aware_utc(now or datetime.now(timezone.utc))
    return current >= aware_utc(previous.first_opened_at) + DAY_DELAY


def current_day(
    rows: dict[int, CourseStageProgress], *, now: datetime | None = None
) -> int:
    current = 1
    for day in range(2, 5):
        if not day_unlocked(rows, day, now=now):
            break
        current = day
    return current


def offer_for_user(db: Session, user_id: uuid.UUID) -> UserOffer | None:
    return db.scalar(
        select(UserOffer).where(
            UserOffer.user_id == user_id,
            UserOffer.stage_code == OFFER_STAGE_CODE,
        )
    )


def open_day(
    db: Session,
    user_id: uuid.UUID,
    day: int,
    *,
    now: datetime | None = None,
) -> CourseStageProgress | None:
    if day not in range(1, 5):
        return None
    current = aware_utc(now or datetime.now(timezone.utc))
    rows = progress_rows(db, user_id)
    if not day_unlocked(rows, day, now=current):
        return None
    progress = rows.get(day)
    if progress is None:
        progress = CourseStageProgress(
            user_id=user_id,
            course_code=COURSE_CODE,
            stage_number=day,
            first_opened_at=current,
            structure_revision_no=1,
            required_step_ids=[],
            required_check_ids=[],
            checkmarks={},
        )
        db.add(progress)
        db.flush()
        course_event(
            db,
            user_id,
            f"day:{day}:opened",
            f"intensive_day_{day}_open",
            details={"day": day},
        )
    if day == 4 and offer_for_user(db, user_id) is None:
        db.add(
            UserOffer(
                user_id=user_id,
                stage_code=OFFER_STAGE_CODE,
                started_at=current,
                expires_at=current + OFFER_DURATION,
                status="active",
                snapshot={"offer_id": OFFER_CODE, "discount_amount": OFFER_DISCOUNT},
            )
        )
        course_event(
            db,
            user_id,
            "offer:day4:received",
            "intensive_discount_received",
            details={"offer_id": OFFER_CODE, "discount_amount": OFFER_DISCOUNT},
        )
    return progress


def mark_assignment_opened(
    db: Session,
    user_id: uuid.UUID,
    day: int,
    platform: str,
    *,
    now: datetime | None = None,
) -> CourseStageProgress | None:
    if day not in range(1, 4) or platform not in PLATFORMS:
        return None
    current = aware_utc(now or datetime.now(timezone.utc))
    progress = progress_rows(db, user_id).get(day)
    if progress is None:
        return None
    if progress.task_opened_at is None:
        progress.task_opened_at = current
        progress.completed_at = current
    course_event(
        db,
        user_id,
        f"day:{day}:post:{platform}",
        "intensive_required_post_open",
        details={"day": day, "messenger": platform},
    )
    return progress


def state_payload(
    db: Session,
    user_id: uuid.UUID,
    platform: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = aware_utc(now or datetime.now(timezone.utc))
    rows = progress_rows(db, user_id)
    offer = offer_for_user(db, user_id)
    return {
        "identified": True,
        "platform": platform,
        "opened_days": sorted(rows),
        "assignment_days": sorted(
            day for day, row in rows.items() if row.task_opened_at is not None
        ),
        "current_day": current_day(rows, now=current),
        "unlocked_days": [
            day for day in range(1, 5) if day_unlocked(rows, day, now=current)
        ],
        "unlock_at": {
            str(day + 1): (aware_utc(row.first_opened_at) + DAY_DELAY).isoformat()
            for day, row in rows.items()
            if day in range(1, 4)
        },
        "offer": (
            {
                "offer_id": OFFER_CODE,
                "discount_amount": OFFER_DISCOUNT,
                "started_at": aware_utc(offer.started_at).isoformat(),
                "expires_at": aware_utc(offer.expires_at).isoformat()
                if offer.expires_at
                else None,
                "active": offer.status == "active"
                and bool(offer.expires_at)
                and aware_utc(offer.expires_at) > current,
            }
            if offer
            else None
        ),
    }


def create_offer_token(
    db: Session, user_id: uuid.UUID, expires_at: datetime
) -> str:
    token = "O" + secrets.token_urlsafe(18)
    db.add(
        MessengerLinkToken(
            user_id=user_id,
            platform="web",
            purpose=OFFER_TOKEN_PURPOSE,
            token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
            expires_at=aware_utc(expires_at),
        )
    )
    db.flush()
    return token


def offer_user_id(db: Session, token: str | None) -> uuid.UUID | None:
    if not token or len(token) > 128:
        return None
    row = db.scalar(
        select(MessengerLinkToken).where(
            MessengerLinkToken.token_hash
            == hashlib.sha256(token.encode("utf-8")).hexdigest(),
            MessengerLinkToken.purpose == OFFER_TOKEN_PURPOSE,
            MessengerLinkToken.consumed_at.is_(None),
        )
    )
    if row is None or aware_utc(row.expires_at) <= datetime.now(timezone.utc):
        return None
    offer = offer_for_user(db, row.user_id)
    if (
        offer is None
        or offer.status != "active"
        or not offer.expires_at
        or aware_utc(offer.expires_at) <= datetime.now(timezone.utc)
    ):
        return None
    return row.user_id


def attributed_path(request: Request, path: str) -> str:
    values = [
        (key, request.query_params[key])
        for key in ATTRIBUTION_KEYS
        if request.query_params.get(key)
    ]
    return f"{path}?{urlencode(values)}" if values else path
