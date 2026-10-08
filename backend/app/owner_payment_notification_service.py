from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from html import escape
import json
import urllib.error
import urllib.request

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import SessionLocal
from app.models import (
    ManagedDocumentVersion, MessengerAccount, OfferCheckout, OwnerPaymentNotification,
    Payment, Product, RecurringSubscription, UserEmail,
)
from app.product_catalog_service import PRODUCT_CATALOG_SEED


EVENT_PAID = "paid"
EVENT_FAILED = "failed"
EVENT_UNFINISHED = "unfinished"
EVENT_SUBSCRIPTION_CANCELLED = "subscription_cancelled"
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


def _is_real_payment(db: Session, payment: Payment, event_kind: str = EVENT_PAID) -> bool:
    allowed = {"pending"} if event_kind == EVENT_UNFINISHED else {"paid", "failed", "cancelled"}
    if payment.payment_status not in allowed:
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
    currency = "₽" if (payment.currency or "RUB") == "RUB" else payment.currency
    amount = f"{payment.amount:,.2f}".replace(",", " ").removesuffix(".00")
    return f"{amount} {currency}"


def _purchase_kind(payment: Payment, checkout: OfferCheckout | None) -> str:
    metadata = payment.raw_payload or {}
    if checkout and checkout.checkout_kind == "manual_service":
        return "Индив. оплата"
    if metadata.get("personal_access_link_id"):
        return "Перс. предложение"
    if checkout and checkout.checkout_kind == "recurring_subscription":
        return "Продление подписки" if metadata.get("recurring_role") == "child" else "Оплата подписки"
    if metadata.get("account_purchase") or (checkout and checkout.checkout_kind == "member_offer"):
        return "Доп. продажа"
    return "Новая покупка"


def _source_label(payment: Payment, checkout: OfferCheckout | None) -> str:
    metadata = payment.raw_payload or {}
    if metadata.get("personal_access_link_id"):
        return "Персональная ссылка"
    if checkout and checkout.checkout_kind == "manual_service":
        return "Страница индивидуальной оплаты"
    if checkout and checkout.checkout_kind == "recurring_subscription":
        return "Автоматическое списание" if metadata.get("recurring_role") == "child" else "Страница подписки"
    place = metadata.get("purchase_place")
    if place in {"homepage", "account", "course"}:
        return {"homepage": "Главная страница", "account": "Личный кабинет", "course": "Материалы Мастер-класса"}[place]
    if metadata.get("account_purchase") or (checkout and checkout.checkout_kind == "member_offer"):
        return "Личный кабинет"
    # Older public checkouts did not record an exact page. Account attachment
    # happens after payment and cannot establish where an invoice was started.
    if checkout and checkout.checkout_kind == "public_site_robokassa":
        return "Публичный сайт (страница не сохранена)"
    if payment.source == "tilda_webhook":
        return "Tilda" + (f" — {payment.form_name_raw}" if payment.form_name_raw else "")
    return "Не сохранено"


def _buyer_user_id(db: Session, payment: Payment):
    if payment.user_id:
        return payment.user_id
    return db.scalar(select(UserEmail.user_id).where(
        UserEmail.email_normalized == (payment.email_at_purchase or "").strip().lower()
    ))


def _product_label(db: Session, payment: Payment) -> str:
    product = db.get(Product, payment.product_id) if payment.product_id else None
    catalog = db.scalar(select(ManagedDocumentVersion.payload).where(
        ManagedDocumentVersion.document_type == "product-catalog",
        ManagedDocumentVersion.document_key == "core",
        ManagedDocumentVersion.is_active.is_(True),
    )) or PRODUCT_CATALOG_SEED
    tariff = next((item for item in catalog.get("tariffs", []) if product and item["code"] == product.code), None)
    if tariff:
        names = {item["code"]: item["shortName"] for item in catalog["products"]}
        return f"{' + '.join(names[code] for code in tariff['products'])} — {payment.product_name_raw}"
    return payment.product_name_raw


def _message_for_payment(
    db: Session,
    payment: Payment,
    event_kind: str,
    failure_reason: str | None = None,
) -> str:
    checkout = _checkout(db, payment)
    kind = _purchase_kind(payment, checkout)
    if event_kind == EVENT_SUBSCRIPTION_CANCELLED:
        heading = f"❌ Отмена подписки · {_amount(payment)} / месяц"
    elif event_kind == EVENT_FAILED:
        heading = f"❌ Ошибка оплаты · {_amount(payment)}"
    elif event_kind == EVENT_UNFINISHED:
        heading = f"⏳ Оплата не завершена · {_amount(payment)}"
    else:
        heading = f"$ {kind} · {_amount(payment)}"
    lines = [f"<b>{escape(heading)}</b>", "", f"Продукт: {escape(_product_label(db, payment))}",
             f"Место покупки: {escape(_source_label(payment, checkout))}", ""]
    if payment.email_at_purchase:
        lines.append(f"Email: {escape(payment.email_at_purchase)}")
    user_id = _buyer_user_id(db, payment)
    accounts = db.scalars(select(MessengerAccount).where(
        MessengerAccount.user_id == user_id, MessengerAccount.platform_user_id.is_not(None),
        MessengerAccount.is_deliverable.is_(True),
    ).order_by(MessengerAccount.platform)).all() if user_id else []
    from app.browser_journey_service import observed_accounts
    observed = (payment.raw_payload or {}).get("observed_browser")
    seen = {(account.platform, account.platform_user_id) for account in accounts}
    accounts.extend(account for account in observed_accounts(db, observed)
                    if (account.platform, account.platform_user_id) not in seen)
    if observed and observed.get("source_bot"):
        lines.append(f"Бот: {escape(str(observed['source_bot']))}")
    if not accounts:
        lines.append("Мессенджер: не привязан")
    for account in accounts:
        name = account.username or account.first_name or account.platform_user_id
        observed_only = (account.platform, account.platform_user_id) not in seen
        provenance = " (из персональной ссылки)" if observed_only else ""
        if account.platform == "telegram":
            url = f"https://t.me/{account.username}" if account.username else f"tg://user?id={account.platform_user_id}"
            label = "Telegram"
        elif account.platform == "max":
            # MAX user IDs are not public profile URLs.
            lines.append(f"MAX: {escape(name)}{provenance or ' (привязан)'}")
            continue
        else:
            continue
        lines.append(f'{label}: <a href="{escape(url, quote=True)}">{escape(name)}</a>{provenance}')
    contact_id = user_id or (observed or {}).get("user_id")
    if contact_id:
        lines.append(f'<a href="https://edabalans.ru/crm?user={escape(str(contact_id), quote=True)}">Карточка клиента</a>')
    if payment.external_order_id:
        lines.extend(("", f"Счёт: {escape(payment.external_order_id)}"))
    if event_kind == EVENT_FAILED and failure_reason:
        lines.append(f"Статус Robokassa: {escape(failure_reason)}")
    if event_kind == EVENT_UNFINISHED:
        lines.append("Через 30 минут после начала счёта оплата не подтверждена. Это не отказ банка.")
    if event_kind == EVENT_SUBSCRIPTION_CANCELLED:
        lines.append("Будущие списания отключены. Отмена не является оплатой или возвратом.")
    metadata = payment.raw_payload or {}
    if kind == "Индив. оплата":
        payer_name = str(metadata.get("payer_name") or "").strip()
        comment = str(metadata.get("comment") or "").strip()
        if payer_name:
            lines.append(f"Имя: {escape(payer_name)}")
        if comment:
            lines.append(f"Комментарий: {escape(comment)}")
    return "\n".join(lines)


def enqueue_owner_payment_notification(
    db: Session,
    payment: Payment,
    event_kind: str,
    *,
    failure_reason: str | None = None,
) -> OwnerPaymentNotification | None:
    if event_kind not in {EVENT_PAID, EVENT_FAILED, EVENT_UNFINISHED, EVENT_SUBSCRIPTION_CANCELLED}:
        raise ValueError("Unsupported owner payment notification event")
    if not _is_real_payment(db, payment, event_kind):
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


def enqueue_unfinished_payment_notification(db: Session, payment: Payment) -> OwnerPaymentNotification | None:
    return enqueue_owner_payment_notification(db, payment, EVENT_UNFINISHED)


def enqueue_subscription_cancelled_notification(db: Session, subscription: RecurringSubscription) -> None:
    payment = db.scalar(select(Payment).where(
        Payment.source == "robokassa", Payment.external_order_id == subscription.parent_invoice_id,
        Payment.payment_status == "paid",
    ))
    if payment:
        enqueue_owner_payment_notification(db, payment, EVENT_SUBSCRIPTION_CANCELLED)


def _queue_messenger_update(db: Session, now: datetime) -> None:
    row = db.scalar(select(OwnerPaymentNotification).join(Payment).join(
        UserEmail, or_(UserEmail.user_id == Payment.user_id, and_(
            Payment.user_id.is_(None), UserEmail.email_normalized == func.lower(Payment.email_at_purchase),
        )),
    ).join(MessengerAccount, MessengerAccount.user_id == UserEmail.user_id).where(
        OwnerPaymentNotification.status == "sent",
        OwnerPaymentNotification.event_kind == EVENT_PAID,
        MessengerAccount.linked_at > OwnerPaymentNotification.sent_at,
    ).order_by(OwnerPaymentNotification.sent_at).limit(1).with_for_update(of=OwnerPaymentNotification))
    if row:
        message = _message_for_payment(db, db.get(Payment, row.payment_id), row.event_kind)
        if message != row.message_text:
            row.message_text = message
            row.status = "retry"
            row.next_attempt_at = now
        else:
            row.sent_at = now


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
        _queue_messenger_update(db, now)
        db.flush()
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
            db.commit()
            return False
        payment = db.get(Payment, row.payment_id)
        if row.event_kind == EVENT_UNFINISHED and (payment.payment_status != "pending" or
                (payment.raw_payload or {}).get("owner_payment_alert_operation_state") in {20, 50, 80, 100}):
            row.status = "cancelled"
            row.next_attempt_at = None
            db.commit()
            return True
        if row.event_kind == EVENT_PAID:
            row.message_text = _message_for_payment(db, db.get(Payment, row.payment_id), row.event_kind)
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
