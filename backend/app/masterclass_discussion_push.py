"""Web Push deliveries for day discussions."""
from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import UTC, datetime, timedelta
import hashlib
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush
import requests
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.account_auth_routes import ACCOUNT_MANAGER_EMAIL, primary_email
from app.config import get_settings
from app.database import SessionLocal
from app.models import MasterclassDiscussionPost as Post
from app.models import MasterclassDiscussionPush as Delivery
from app.models import MasterclassDiscussionSubscription as Subscription

PUSH_TITLES = {"reply": "Сергей ответил на ваш вопрос", "day": "Новое сообщение в обсуждении дня {day}"}
logger = logging.getLogger(__name__)


def permitted_endpoint(value: str) -> bool:
    if not value.isascii() or any(char.isspace() or ord(char) < 32 or char == chr(92) for char in value):
        return False
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        return (
            url.scheme == "https" and url.username is None and url.password is None
            and url.netloc.lower() in {host, host+":443"} and not url.fragment and url.path.startswith("/")
            and (
                host in {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"}
                or host.endswith((".web.push.apple.com", ".notify.windows.com"))
            )
        )
    except ValueError:
        return False


def valid_keys(p256dh: str, auth: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(p256dh + "=" * (-len(p256dh) % 4))
        secret = base64.urlsafe_b64decode(auth + "=" * (-len(auth) % 4))
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
        return len(raw) == 65 and len(secret) == 16
    except (ValueError, binascii.Error):
        return False


def endpoint_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def key_path() -> Path:
    return Path(get_settings().masterclass_discussion_media_dir) / "webpush-vapid.pem"


def public_key() -> str:
    key = key_path()
    if not key.exists():
        material = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        with os.fdopen(os.open(key, os.O_WRONLY | os.O_EXCL | os.O_CREAT, 0o600), "wb") as out:
            out.write(material)
    private = serialization.load_pem_private_key(key.read_bytes(), password=None)
    raw = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def add_delivery(db: Session, subscription: Subscription, kind: str, day: int, post_id: int | None,
                 dedupe: str, *, probe: bool = False) -> None:
    url = f"/lk?account_app=masterclass-course&course_day={day}&discussion_open=1"
    if post_id is not None:
        url += f"&discussion_post={post_id}"
    db.add(Delivery(
        subscription_id=subscription.id,
        dedupe=dedupe,
        payload={"kind": kind, "title": PUSH_TITLES[kind].format(day=day),
                 "body": "Проверка уведомлений" if probe else "Открыть обсуждение", "url": url},
        due_at=datetime.now(UTC),
    ))


def enqueue_test(db: Session, subscription: Subscription, kind: str, nonce: UUID, day: int, post_id: int | None) -> None:
    dedupe = f"pilot:{subscription.id}:{kind}:{nonce}"
    if not db.scalar(select(Delivery.id).where(Delivery.dedupe == dedupe)):
        add_delivery(db, subscription, kind, day, post_id, dedupe, probe=True)


def enqueue_post(db: Session, post: Post, question: Post | None, *, is_author: bool) -> None:
    subscriptions = db.scalars(select(Subscription).where(Subscription.user_id != post.author_id))
    for subscription in subscriptions:
        # Match the current owner-only access gate, including delivery of existing subscriptions.
        if primary_email(db, subscription.user_id) != ACCOUNT_MANAGER_EMAIL:
            continue
        reply_to_subscriber = is_author and question is not None and question.author_id == subscription.user_id
        if reply_to_subscriber and subscription.replies:
            kind = "reply"
        elif subscription.new_posts:
            kind = "day"
        else:
            continue
        add_delivery(db, subscription, kind, post.day_number, post.id, f"post:{subscription.id}:{post.id}")


class NoRedirectSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


def deliver_one() -> bool:
    settings = get_settings()
    if not settings.masterclass_discussion_pilot or not key_path().is_file():
        return False
    with SessionLocal() as db:
        item = db.scalar(
            select(Delivery).where(Delivery.processed.is_(False), Delivery.due_at <= datetime.now(UTC))
            .order_by(Delivery.due_at).limit(1).with_for_update(skip_locked=True)
        )
        if item is None:
            return False
        subscriber = db.get(Subscription, item.subscription_id)
        kind = item.payload["kind"]
        if (
            not subscriber or primary_email(db, subscriber.user_id) != ACCOUNT_MANAGER_EMAIL
            or not permitted_endpoint(subscriber.subscription["endpoint"])
            or (kind == "reply" and not subscriber.replies)
            or (kind == "day" and not subscriber.new_posts)
        ):
            item.processed = True
            db.commit()
            return True
        item.attempts += 1
        try:
            with NoRedirectSession() as client:
                client.trust_env = False
                webpush(
                    subscription_info=subscriber.subscription,
                    data=json.dumps({**item.payload, "tag":item.dedupe}, ensure_ascii=False),
                    vapid_private_key=str(key_path()),
                    vapid_claims={"sub": f"mailto:{ACCOUNT_MANAGER_EMAIL}"},
                    requests_session=client,
                    timeout=8,
                    ttl=3600,
                )
        except WebPushException as error:
            code = error.response.status_code if error.response is not None else 503
            if code in (404, 410):
                db.delete(subscriber)
            elif code == 429 or code >= 500:
                item.processed = item.attempts >= 3
                item.due_at = datetime.now(UTC) + timedelta(minutes=2 * item.attempts)
            else:
                item.processed = True
        except requests.RequestException:
            item.processed = item.attempts >= 3
            item.due_at = datetime.now(UTC) + timedelta(minutes=2 * item.attempts)
        except (ValueError, binascii.Error):
            item.processed = True
        else:
            item.processed = True
        db.commit()
        return True


async def worker(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(deliver_one)
        except (OSError, SQLAlchemyError):
            logger.warning("Discussion notification worker could not complete a tick")
        try:
            await asyncio.wait_for(stop.wait(), 5)
        except TimeoutError:
            pass
