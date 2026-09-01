from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, CrmMessengerAccount, TelegramLoginAttempt

TTL_SECONDS = 15 * 60


def _decode_payload(payload: str, secret: str) -> bytes | None:
    if not payload.startswith("I") or not secret:
        return None
    try:
        raw = base64.urlsafe_b64decode(payload[1:] + "=" * (-len(payload[1:]) % 4))
    except (ValueError, TypeError):
        return None
    if len(raw) != 32:
        return None
    timestamp, nonce, supplied = struct.unpack(">I16s12s", raw)
    expected = hmac.new(secret.encode(), b"I" + raw[:20], hashlib.sha256).digest()[:12]
    if not hmac.compare_digest(supplied, expected):
        return None
    now = int(time.time())
    if timestamp > now + 60 or now - timestamp > TTL_SECONDS:
        return None
    return nonce


def consume_web_login(
    session: Session,
    contact: Contact,
    telegram: dict,
    payload: str,
    secret: str,
) -> tuple[bool, str, dict]:
    if not payload.startswith("I"):
        return False, "not_web_login", {}
    nonce = _decode_payload(payload, secret)
    if nonce is None:
        return True, "web_login_invalid", {}
    account = session.scalar(select(CrmMessengerAccount).where(
        CrmMessengerAccount.platform == "telegram",
        CrmMessengerAccount.platform_user_id == str(telegram["id"]),
    ))
    if not account or not contact.user_id:
        return True, "web_login_identity_failed", {}
    digest = hashlib.sha256(nonce).hexdigest()
    existing = session.scalar(select(TelegramLoginAttempt).where(TelegramLoginAttempt.nonce_hash == digest))
    if existing:
        return True, "web_login_used", {}
    now = datetime.now(UTC)
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(TelegramLoginAttempt(
        nonce_hash=digest,
        user_id=account.user_id,
        telegram_user_id=str(telegram["id"]),
        username=telegram.get("username"),
        first_name=telegram.get("first_name"),
        verification_code_hash=hashlib.sha256(code.encode()).hexdigest(),
        expires_at=now + timedelta(minutes=15),
        consumed_at=now,
    ))
    return True, "web_login_code", {"login_code": code}
