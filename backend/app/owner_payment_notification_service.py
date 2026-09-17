from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import urllib.error
import urllib.request

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import SessionLocal
from app.models import OfferCheckout, OwnerPaymentNotification, Payment


EVENT_PAID = "paid"
EVENT_FAILED = "failed"
LIVE_PROBE_CHECKOUT_KIND = "robokassa_live_probe"


def owner_payment_alert_configuration_error(settings: Settings) -> str | None:
    if not settings.payment_owner_alerts_enabled:
        return None
    required = {
        "APP_AUTH_SECRET": settings.app_auth_secret,
        "PAYMENT_OWNER_ALERTS_ENDPOINT": settings.payment_owner_alerts_endpoint,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        return f"owner payment alerts are missing: {', '.join(missing)}"
    return None


def _checkout(db: Session, payment: Payment) -> OfferCheckout | None:
    return db.scalar(select(OfferCheckout).where(OfferCheckout.payment_id == payment.id))


def _is_real_payment(db: Session, payment: Payment) -> bool:
    if payment.payment_status not in {"paid", "failed", "cancelled"}:
        return False
    metadata = payment.raw_payload or {}
    integration = metadata.get("integration") if isinstance(metadata, dict) else None
    if isinstance(integration, dict) and (integration.get("test_mode") or integration.get("live_probe")):
        return False
    if isinstance(metadata, dict) and metadata.get("test_mode"):
        return False
    checkout = _checkout(db, payment)
    return checkout is None or checkout.checkout_kind != LIVE_PROBE_CHECKOUT_KIND


def _amount(payment: Payment) -> str:
    if payment.amount is None:
        return "не указана"
    currency = payment.currency or "RUB"
    return f"{payment.amount:.2f} {currency}".replace(".00 ", " ")


def _source_label(payment: Payment, checkout: OfferCheckout | None) -> str:
    if checkout and checkout.checkout_kind == "manual_service":
        return "свободная оплата услуги"
    if checkout and checkout.checkout_kind == "recurring_subscription":
        metadata = payment.raw_payload or {}
        if isinstance(metadata, dict) and metadata.get("recurring_role") == "child":
            return "повторное списание подписки"
        return "первичная оплата подписки"
    if payment.source == "tilda_webhook":
        return "оплата через Tilda"
    if checkout and checkout.user_id:
        return "оплата из личного кабинета"
    return "прямая оплата с сайта"


def _message_for_payment(
    db: Session,
    payment: Payment,
    event_kind: str,
    failure_reason: str | None = None,
) -> str:
    checkout = _checkout(db, payment)
    source = _source_label(payment, checkout)
    if event_kind == EVENT_PAID:
        lines = ["Новая оплата", f"Сумма: {_amount(payment)}"]
    else:
        lines = ["Ошибка оплаты", f"Сумма: {_amount(payment)}"]
    lines.extend((f"Что: {payment.product_name_raw}", f"Источник: {source}"))
    if payment.email_at_purchase:
        lines.append(f"Email: {payment.email_at_purchase}")
    if payment.external_order_id:
        lines.append(f"Счёт: {payment.external_order_id}")
    if event_kind == EVENT_FAILED and failure_reason:
        lines.append(f"Статус Robokassa: {failure_reason}")
    metadata = payment.raw_payload or {}
    if source == "свободная оплата услуги" and isinstance(metadata, dict):
        payer_name = str(metadata.get("payer_name") or "").strip()
        comment = str(metadata.get("comment") or "").strip()
        if payer_name:
            lines.append(f"Имя: {payer_name}")
        if comment:
            lines.append(f"Назначение: {comment}")
    return "\n".join(lines)


def enqueue_owner_payment_notification(
    db: Session,
    payment: Payment,
    event_kind: str,
    *,
    failure_reason: str | None = None,
) -> OwnerPaymentNotification | None:
    if event_kind not in {EVENT_PAID, EVENT_FAILED}:
        raise ValueError("Unsupported owner payment notification event")
    if not _is_real_payment(db, payment):
        return None
    existing = db.scalar(
        select(OwnerPaymentNotification).where(
            OwnerPaymentNotification.payment_id == payment.id,
            OwnerPaymentNotification.event_kind == event_kind,
        )
    )
    if existing is not None:
        return existing
    row = OwnerPaymentNotification(
        payment_id=payment.id,
        event_kind=event_kind,
        message_text=_message_for_payment(db, payment, event_kind, failure_reason),
        status="pending",
        next_attempt_at=datetime.now(timezone.utc),
    )
    db.add(row)
    return row


def enqueue_paid_payment_notification(db: Session, payment: Payment) -> OwnerPaymentNotification | None:
    return enqueue_owner_payment_notification(db, payment, EVENT_PAID)


def enqueue_failed_payment_notification(
    db: Session, payment: Payment, reason: str
) -> OwnerPaymentNotification | None:
    return enqueue_owner_payment_notification(
        db, payment, EVENT_FAILED, failure_reason=reason
    )


def _signature(notification_id: str, message_text: str, secret: str) -> str:
    payload = f"{notification_id}\n{message_text}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _deliver(settings: Settings, row: OwnerPaymentNotification) -> str:
    body = json.dumps(
        {"notification_id": str(row.id), "message_text": row.message_text},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        settings.payment_owner_alerts_endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Edabalans-Payment-Signature": _signature(
                str(row.id), row.message_text, settings.app_auth_secret
            ),
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"owner alert relay HTTP {response.status}")
        payload = json.loads(response.read(8_192).decode("utf-8"))
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError("owner alert relay rejected notification")
    return str(payload.get("message_id") or "")[:128]


def send_one_owner_payment_notification(settings: Settings) -> bool:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        row = db.scalar(
            select(OwnerPaymentNotification)
            .where(
                OwnerPaymentNotification.status.in_(("pending", "retry")),
                OwnerPaymentNotification.next_attempt_at <= now,
            )
            .order_by(OwnerPaymentNotification.next_attempt_at, OwnerPaymentNotification.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return False
        try:
            message_id = _deliver(settings, row)
        except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            row.attempt_count += 1
            row.status = "retry"
            row.last_error = str(exc)[:1000]
            row.next_attempt_at = now + timedelta(
                seconds=min(3600, 60 * (2 ** min(row.attempt_count, 6)))
            )
        except Exception as exc:
            row.attempt_count += 1
            row.status = "retry"
            row.last_error = str(exc)[:1000]
            row.next_attempt_at = now + timedelta(
                seconds=min(3600, 60 * (2 ** min(row.attempt_count, 6)))
            )
        else:
            row.attempt_count += 1
            row.status = "sent"
            row.sent_at = now
            row.next_attempt_at = None
            row.delivery_message_id = message_id or None
            row.last_error = None
        db.commit()
        return True


async def owner_payment_notification_worker(settings: Settings, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            processed = await asyncio.to_thread(send_one_owner_payment_notification, settings)
        except Exception:
            # A transient database failure must not silently terminate the
            # background worker. Unfinished outbox rows remain claimable.
            processed = False
        if processed:
            continue
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.payment_owner_alerts_poll_seconds
            )
        except asyncio.TimeoutError:
            pass
