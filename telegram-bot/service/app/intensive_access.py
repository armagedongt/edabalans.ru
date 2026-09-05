from __future__ import annotations

import base64
import hashlib
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MessengerLinkToken


PURPOSE = "intensive_access"
TOKEN_TTL = timedelta(days=100 * 365)
PLATFORMS = {"telegram", "max"}


def intensive_token(token_id: str) -> str:
    return "E" + base64.urlsafe_b64encode(uuid.UUID(token_id).bytes).decode().rstrip("=")


def intensive_access_url(public_url: str, token: str) -> str:
    parts = urlsplit(public_url)
    if parts.path.rstrip("/").endswith("/i") and not parts.query:
        path = f"{parts.path.rstrip('/')}/{quote(token, safe='')}"
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    separator = "&" if "?" in public_url else "?"
    return f"{public_url}{separator}{urlencode({'i': token})}"


def personal_tracking_values(
    session: Session,
    *,
    user_id: str,
    platform: str,
    public_url: str,
    channel_post_numbers: Iterable[int] = (),
) -> dict[str, str]:
    intensive_url, row = get_or_create_intensive_access_link(
        session,
        user_id=user_id,
        platform=platform,
        public_url=public_url,
    )
    token = intensive_token(str(row.id))
    parts = urlsplit(public_url)
    root = urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")
    encoded = quote(token, safe="")
    values = {
        "personal_intensive_url": intensive_url,
        "personal_masterclass_url": f"{root}/m/{encoded}",
    }
    for post_number in channel_post_numbers:
        if post_number < 1 or post_number > 9_999_999:
            raise ValueError("invalid Telegram channel post number")
        values[f"personal_channel_post_{post_number}_url"] = (
            f"{root}/p/{post_number}/{encoded}"
        )
    return values


def create_intensive_access_link(
    session: Session,
    *,
    user_id: str,
    platform: str,
    public_url: str,
    now: datetime | None = None,
    token: str | None = None,
    row_id: str | None = None,
) -> tuple[str, MessengerLinkToken]:
    if platform not in PLATFORMS:
        raise ValueError("unsupported intensive platform")
    if not public_url.startswith("https://"):
        raise ValueError("intensive public URL must use HTTPS")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    row_id = row_id or str(uuid.uuid4())
    token = token or intensive_token(row_id)
    if not token.startswith("E") or len(token) > 128:
        raise ValueError("invalid intensive access token")
    row = MessengerLinkToken(
        id=row_id,
        user_id=user_id,
        platform=platform,
        purpose=PURPOSE,
        token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
        expires_at=current + TOKEN_TTL,
    )
    session.add(row)
    session.flush()
    return intensive_access_url(public_url, token), row


def get_or_create_intensive_access_link(
    session: Session,
    *,
    user_id: str,
    platform: str,
    public_url: str,
    now: datetime | None = None,
) -> tuple[str, MessengerLinkToken]:
    if platform not in PLATFORMS:
        raise ValueError("unsupported intensive platform")
    if not public_url.startswith("https://"):
        raise ValueError("intensive public URL must use HTTPS")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    rows = session.scalars(
        select(MessengerLinkToken)
        .where(
            MessengerLinkToken.user_id == user_id,
            MessengerLinkToken.platform == platform,
            MessengerLinkToken.purpose == PURPOSE,
            MessengerLinkToken.expires_at > current,
        )
        .order_by(MessengerLinkToken.created_at.desc())
    )
    for row in rows:
        token = intensive_token(row.id)
        if row.token_hash == hashlib.sha256(token.encode("ascii")).hexdigest():
            return intensive_access_url(public_url, token), row
    return create_intensive_access_link(
        session,
        user_id=user_id,
        platform=platform,
        public_url=public_url,
        now=current,
    )
