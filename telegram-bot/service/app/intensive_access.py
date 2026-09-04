from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from .models import MessengerLinkToken


PURPOSE = "intensive_access"
TOKEN_TTL = timedelta(days=2 * 365)
PLATFORMS = {"telegram", "max"}


def create_intensive_access_link(
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
    token = "E" + secrets.token_urlsafe(18)
    row = MessengerLinkToken(
        user_id=user_id,
        platform=platform,
        purpose=PURPOSE,
        token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
        expires_at=current + TOKEN_TTL,
    )
    session.add(row)
    session.flush()
    separator = "&" if "?" in public_url else "?"
    query = urlencode({"i": token})
    return f"{public_url}{separator}{query}", row
