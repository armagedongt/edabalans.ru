"""Recognition for reader invitations only: never an account or course credential."""
from __future__ import annotations

import base64
import hashlib
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.intensive_web_access import access_token_row, aware_utc, ACCESS_PURPOSE, PLATFORMS
from app.models import CourseEvent, MessengerAccount, MessengerLinkToken, Payment, User
from app.course_access_service import active_resource_codes
from app.product_identity import CONFIRMED_PAYMENT_STATUSES
from app.public_site_content_service import reader_subscription_document

COOKIE = "edabalans_reader"
COOKIE_AGE = 30 * 24 * 60 * 60
ROOTS = ("edabalans.ru", "xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai")


def _cipher(secret: str) -> Fernet:
    key = hashlib.sha256(("reader-only-v1\0" + secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _active_user(db: Session, row: MessengerLinkToken) -> User | None:
    user = db.get(User, row.user_id)
    return user if user and user.status == "active" and user.merged_into_user_id is None else None


def recognize_reader(db: Session, request: Request, response: Response, secret: str, token: str) -> bool:
    """Reuse a verified personal bot link, without creating rights or a login."""
    try:
        row = access_token_row(db, token)
    except UnicodeEncodeError:
        return False
    if not secret or row is None or _active_user(db, row) is None:
        return False
    expires = min(int(time.time()) + COOKIE_AGE, int(aware_utc(row.expires_at).timestamp()))
    # Legacy bot codes can be derived from row UUIDs: never expose that UUID.
    value = _cipher(secret).encrypt(row.id.bytes).decode("ascii")
    host = (request.url.hostname or "").encode("idna").decode("ascii").lower()
    domain = next((root for root in ROOTS if host == root or host.endswith("." + root)), None)
    response.set_cookie(COOKIE, value,
                        max_age=max(0, expires - int(time.time())), path="/", domain=domain,
                        secure=True, httponly=True, samesite="lax")
    return True


def reader_user(db: Session, request: Request, secret: str) -> User | None:
    value = request.cookies.get(COOKIE, "")
    if not secret or len(value) > 256:
        return None
    try:
        raw = _cipher(secret).decrypt(value.encode("ascii"), ttl=COOKIE_AGE)
        row_id = uuid.UUID(bytes=raw)
    except (InvalidToken, UnicodeEncodeError, ValueError, TypeError):
        return None
    row = db.get(MessengerLinkToken, row_id)
    if row is None or row.purpose != ACCESS_PURPOSE or row.platform not in PLATFORMS:
        return None
    if aware_utc(row.expires_at) <= datetime.now(timezone.utc):
        return None
    return _active_user(db, row)


def _subscription(account: MessengerAccount | None) -> bool | None:
    # A stale observation is unknown, not proof of current membership.
    if account and account.subscription_checked_at:
        age = datetime.now(timezone.utc) - aware_utc(account.subscription_checked_at)
        if timedelta(0) <= age <= timedelta(hours=24):
            return {"subscribed": True, "not_subscribed": False}.get(account.subscription_status)
    return None


def reader_context(db: Session, request: Request, secret: str) -> dict:
    payload = reader_subscription_document(db).payload
    destinations = payload["settings"]
    user = reader_user(db, request, secret)
    accounts = {account.platform: account for account in db.scalars(
        select(MessengerAccount).where(MessengerAccount.user_id == user.id,
                                      MessengerAccount.is_deliverable.is_(True))
    )} if user else {}
    subscribed = _subscription(accounts.get("telegram"))
    source_platform = {"tg": "telegram", "max": "max"}.get(request.query_params.get("from"))
    source_subscription = _subscription(accounts.get(source_platform)) if source_platform else subscribed
    buyer = False
    read_percent = 0
    if user:
        buyer = bool(db.scalar(select(Payment.id).where(
            Payment.user_id == user.id,
            Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES),
        ).limit(1))) or bool(active_resource_codes(db, user.id) & {
            "ACCESS_MASTERCLASS", "ACCESS_MASTERCLASS_LEGACY"})
        read_percent = db.scalar(select(func.max(CourseEvent.details["viewed_percent"].as_integer())).where(
            CourseEvent.user_id == user.id, CourseEvent.course_code == "intensive",
            CourseEvent.event_type.in_(("intensive_onepage_progress", "intensive_onepage_heading",
                                       "intensive_onepage_reading_start")),
        )) or 0
    if buyer or (source_platform and source_subscription is not False):
        variant = "hidden"
    elif read_percent > 75:
        variant = "hidden" if source_subscription is True else "subscribe"
    else:
        variant = "full"
    return {
        "recognized": user is not None,
        "show_subscription": variant != "hidden",
        "subscription_variant": variant,
        "copy_html": payload["variants"].get(variant, ""),
        "footer_html": payload.get("footer_html", "") if variant == "full" else "",
        "telegram": {"url": destinations["telegram_url"], "subscribed": subscribed},
        "max": {"url": destinations["max_url"]},
    }
