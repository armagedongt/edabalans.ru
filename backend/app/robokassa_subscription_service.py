from __future__ import annotations

import asyncio
import calendar
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage
import hashlib
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.account_onboarding_service import _send_message
from app.database import SessionLocal
from app.models import (
    AccountCredential,
    OfferCheckout,
    Payment,
    PriceEntry,
    PricingVersion,
    RecurringSubscription,
    User,
    UserEmail,
)
from app.pricing_service import amount_value, pricing_entry_map
from app.robokassa_service import (
    RobokassaError,
    SOURCE,
    _amount_text,
    _encoded,
    _invoice_id,
    _payment_fields,
    _receipt,
    _require_checkout_settings,
    normalize_checkout_email,
)


SUBSCRIPTION_PRICE_CODE = "subscription.coaching.monthly"
SUBSCRIPTION_PRODUCT_CODE = "COACHING"
SUBSCRIPTION_TITLE = "Индивидуальное сопровождение — 1 месяц"
SUBSCRIPTION_CHECKOUT_KIND = "recurring_subscription"
SUCCESS_KIND_SUBSCRIPTION = "coaching_subscription"


def recurring_subscription_configuration_error(settings: Settings) -> str | None:
    if not settings.robokassa_recurring_worker_enabled:
        return None
    required = {
        "ROBOKASSA_MERCHANT_LOGIN": settings.robokassa_merchant_login,
        "ROBOKASSA_PASSWORD_1": settings.robokassa_password_1,
        "ROBOKASSA_PASSWORD_2": settings.robokassa_password_2,
        "SMTP_HOST": settings.smtp_host,
        "SMTP_FROM_EMAIL": settings.smtp_from_email,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        return f"recurring subscriptions are missing: {', '.join(missing)}"
    if settings.robokassa_test_mode:
        return "recurring subscription worker cannot run in Robokassa test mode"
    return None


def add_calendar_month(value: datetime) -> datetime:
    """Keep the billing day where possible and clamp it at month end."""
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def subscription_entry(db: Session, version: PricingVersion) -> PriceEntry:
    entry = pricing_entry_map(db, version).get(SUBSCRIPTION_PRICE_CODE)
    if entry is None or entry.section != "subscriptions" or not entry.enabled:
        raise RobokassaError("Подписка сейчас недоступна")
    if entry.sale_amount <= 0:
        raise RobokassaError("Цена подписки настроена некорректно")
    return entry


def public_subscription_offer(db: Session, version: PricingVersion) -> dict:
    entry = subscription_entry(db, version)
    return {
        "ok": True,
        "price_code": entry.code,
        "title": entry.name,
        "amount": amount_value(entry.sale_amount),
        "currency": entry.currency,
        "period": "month",
        "pricing_version": version.version_number,
    }


def _existing_subscription(
    db: Session, user: User, email: str, now: datetime
) -> RecurringSubscription | None:
    return db.scalar(
        select(RecurringSubscription)
        .where(
            RecurringSubscription.product_code == SUBSCRIPTION_PRODUCT_CODE,
            or_(
                RecurringSubscription.user_id == user.id,
                RecurringSubscription.email_normalized == email,
            ),
            or_(
                RecurringSubscription.status.in_({"active", "charging"}),
                and_(
                    RecurringSubscription.status == "pending",
                    RecurringSubscription.created_at > now - timedelta(hours=2),
                ),
                RecurringSubscription.current_period_end > now,
            ),
        )
        .order_by(RecurringSubscription.created_at.desc())
        .limit(1)
    )


def create_subscription_payment(
    db: Session,
    settings: Settings,
    version: PricingVersion,
    email_original: str,
    *,
    terms_ip: str | None,
    terms_user_agent: str | None,
) -> dict:
    _require_checkout_settings(settings)
    email = normalize_checkout_email(email_original)
    now = datetime.now(timezone.utc)
    user = db.scalar(
        select(User)
        .join(UserEmail, UserEmail.user_id == User.id)
        .where(
            UserEmail.email_normalized == email,
            User.status == "active",
            User.merged_into_user_id.is_(None),
        )
    )
    if user is None or db.get(AccountCredential, user.id) is None:
        # Do not reveal through a public checkout whether an email is registered
        # or whether that account has finished credential provisioning.
        raise RobokassaError(
            "Не удалось подтвердить готовый аккаунт. Проверьте email или сначала войдите в личный кабинет"
        )
    if _existing_subscription(db, user, email, now) is not None:
        raise RobokassaError(
            "Для этой почты уже есть действующая или ожидающая оплаты подписка"
        )
    entry = subscription_entry(db, version)
    expires_at = now + timedelta(hours=2)
    payment_id = uuid.uuid4()
    invoice_id = str(_invoice_id(payment_id))
    payment = Payment(
        id=payment_id,
        user_id=user.id,
        pricing_version_id=version.id,
        price_entry_code=entry.code,
        source=SOURCE,
        external_order_id=invoice_id,
        email_at_purchase=email,
        product_name_raw=entry.name,
        amount=entry.sale_amount,
        amount_is_estimated=False,
        currency=entry.currency,
        payment_status="pending",
        payment_system="robokassa",
        raw_payload={"test_mode": settings.robokassa_test_mode},
    )
    subscription = RecurringSubscription(
        user_id=user.id,
        product_code=SUBSCRIPTION_PRODUCT_CODE,
        price_entry_code=entry.code,
        pricing_version_id=version.id,
        email_normalized=email,
        amount=entry.sale_amount,
        currency=entry.currency,
        status="pending",
        parent_invoice_id=invoice_id,
        terms_accepted_at=now,
        terms_ip=(terms_ip or "")[:64] or None,
        terms_user_agent=(terms_user_agent or "")[:500] or None,
    )
    checkout = OfferCheckout(
        user_id=user.id,
        checkout_kind=SUBSCRIPTION_CHECKOUT_KIND,
        pricing_version_id=version.id,
        price_entry_code=entry.code,
        offer_code=entry.code,
        title=entry.name,
        items=[],
        amount=entry.sale_amount,
        expires_at=expires_at,
        payment_id=payment.id,
    )
    db.add(payment)
    db.flush()
    db.add(subscription)
    db.flush()
    db.add(checkout)
    db.flush()
    payment.raw_payload = {
        "test_mode": settings.robokassa_test_mode,
        "account_purchase": True,
        "success_kind": SUCCESS_KIND_SUBSCRIPTION,
        "subscription_id": str(subscription.id),
        "recurring_role": "parent",
        "checkout_id": str(checkout.id),
    }
    fields = _payment_fields(settings, payment, entry.name, email, expires_at)
    fields["Recurring"] = "true"
    db.commit()
    return {
        "ok": True,
        "invoice_id": invoice_id,
        "amount": amount_value(entry.sale_amount),
        "price_code": entry.code,
        "pricing_version": version.version_number,
        "test_mode": settings.robokassa_test_mode,
        "expires_at": expires_at.isoformat(),
        "payment_form": {
            "action": settings.robokassa_payment_url,
            "method": "POST",
            "fields": fields,
        },
    }


def apply_confirmed_subscription_payment(
    db: Session,
    payment: Payment,
    user: User,
    occurred_at: datetime,
    metadata: dict,
    *,
    is_test_payment: bool,
) -> None:
    raw_id = metadata.get("subscription_id")
    try:
        subscription_id = uuid.UUID(str(raw_id))
    except (TypeError, ValueError) as exc:
        raise RobokassaError("В платеже отсутствует идентификатор подписки") from exc
    subscription = db.scalar(
        select(RecurringSubscription)
        .where(RecurringSubscription.id == subscription_id)
        .with_for_update()
    )
    if subscription is None:
        raise RobokassaError("Подписка для платежа не найдена")
    subscription.user_id = user.id
    subscription.email_normalized = normalize_checkout_email(payment.email_at_purchase or "")
    subscription.pending_invoice_id = None
    subscription.charge_started_at = None
    subscription.next_status_check_at = None
    subscription.last_error = None
    if is_test_payment:
        subscription.status = "test_paid"
        subscription.successful_payments = max(subscription.successful_payments, 1)
        return
    previous_status = subscription.status
    start = occurred_at
    if metadata.get("recurring_role") == "child" and subscription.current_period_end:
        current_end = subscription.current_period_end
        if current_end.tzinfo is None:
            current_end = current_end.replace(tzinfo=timezone.utc)
        start = max(current_end, occurred_at)
    subscription.current_period_start = start
    subscription.current_period_end = add_calendar_month(start)
    subscription.successful_payments += 1
    if previous_status == "cancelled" or subscription.cancelled_at is not None:
        subscription.status = "cancelled"
        subscription.next_charge_at = None
    else:
        subscription.status = "active"
        subscription.next_charge_at = subscription.current_period_end


def subscription_for_user(db: Session, user: User) -> RecurringSubscription | None:
    return db.scalar(
        select(RecurringSubscription)
        .where(
            RecurringSubscription.user_id == user.id,
            RecurringSubscription.product_code == SUBSCRIPTION_PRODUCT_CODE,
        )
        .order_by(RecurringSubscription.created_at.desc())
        .limit(1)
    )


def serialize_subscription(row: RecurringSubscription | None) -> dict:
    if row is None:
        return {"exists": False}
    return {
        "exists": True,
        "status": (
            "cancellation_pending"
            if row.status == "charging" and row.cancelled_at is not None
            else row.status
        ),
        "amount": amount_value(row.amount),
        "currency": row.currency,
        "current_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
        "next_charge_at": row.next_charge_at.isoformat() if row.next_charge_at else None,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "successful_payments": row.successful_payments,
    }


def cancel_subscription(db: Session, user: User) -> RecurringSubscription:
    row = db.scalar(
        select(RecurringSubscription)
        .where(
            RecurringSubscription.user_id == user.id,
            RecurringSubscription.product_code == SUBSCRIPTION_PRODUCT_CODE,
        )
        .order_by(RecurringSubscription.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if row is None:
        raise RobokassaError("У вас нет подписки на сопровождение")
    if row.status == "cancelled":
        return row
    if row.status not in {"active", "charging"}:
        raise RobokassaError("Эту подписку сейчас нельзя отключить")
    row.cancelled_at = datetime.now(timezone.utc)
    row.cancellation_source = "self_service"
    row.next_charge_at = None
    if row.status == "active":
        row.status = "cancelled"
    db.commit()
    return row


def _recurring_charge_fields(
    settings: Settings,
    subscription: RecurringSubscription,
    payment: Payment,
) -> dict[str, str]:
    merchant, password = _require_checkout_settings(settings)
    if not subscription.parent_invoice_id or not payment.external_order_id or payment.amount is None:
        raise RobokassaError("Не хватает данных для повторного списания")
    receipt = _encoded(_receipt(settings, SUBSCRIPTION_TITLE, payment.amount))
    values = [
        merchant,
        _amount_text(payment.amount),
        payment.external_order_id,
        receipt,
        settings.robokassa_result_url_2,
        password,
    ]
    signature = hashlib.new(
        settings.robokassa_hash_algorithm.strip().lower(), ":".join(values).encode("utf-8")
    ).hexdigest()
    return {
        "MerchantLogin": merchant,
        "OutSum": _amount_text(payment.amount),
        "InvoiceID": payment.external_order_id,
        "PreviousInvoiceID": subscription.parent_invoice_id,
        "Description": SUBSCRIPTION_TITLE,
        "Email": subscription.email_normalized,
        "Culture": "ru",
        "Encoding": "utf-8",
        "Receipt": receipt,
        "ResultUrl2": settings.robokassa_result_url_2,
        "SignatureValue": signature,
        "IsTest": "1" if settings.robokassa_test_mode else "0",
    }


def _operation_state(settings: Settings, invoice_id: str) -> tuple[int, int | None]:
    merchant = settings.robokassa_merchant_login.strip()
    password = settings.robokassa_password_2.strip()
    if not merchant or not password:
        raise RobokassaError("Для проверки повторных платежей не настроен пароль Robokassa №2")
    algorithm = settings.robokassa_hash_algorithm.strip().lower()
    signature = hashlib.new(
        algorithm, f"{merchant}:{invoice_id}:{password}".encode("utf-8")
    ).hexdigest()
    url = settings.robokassa_operation_state_url + "?" + urllib.parse.urlencode(
        {"MerchantLogin": merchant, "InvoiceID": invoice_id, "Signature": signature}
    )
    with urllib.request.urlopen(url, timeout=20) as response:
        root = ET.fromstring(response.read(65_536))

    def value(path_end: str) -> str | None:
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] == path_end and node.text:
                return node.text.strip()
        return None

    result_code = int(value("Code") or 1000)
    state_code = None
    if result_code == 0:
        state = next(
            (node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "State"),
            None,
        )
        if state is not None:
            state_text = next(
                (
                    node.text.strip()
                    for node in state
                    if node.tag.rsplit("}", 1)[-1] == "Code" and node.text
                ),
                None,
            )
            state_code = int(state_text) if state_text is not None else None
    return result_code, state_code


def check_one_pending_charge(settings: Settings) -> bool:
    if settings.robokassa_test_mode:
        return False
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        subscription = db.scalar(
            select(RecurringSubscription)
            .where(
                RecurringSubscription.status == "charging",
                RecurringSubscription.pending_invoice_id.is_not(None),
                RecurringSubscription.next_status_check_at.is_not(None),
                RecurringSubscription.next_status_check_at <= now,
            )
            .order_by(RecurringSubscription.next_status_check_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if subscription is None:
            return False
        invoice_id = subscription.pending_invoice_id or ""
        payment = db.scalar(
            select(Payment).where(
                Payment.source == SOURCE, Payment.external_order_id == invoice_id
            )
        )
        checkout = (
            db.scalar(select(OfferCheckout).where(OfferCheckout.payment_id == payment.id))
            if payment is not None
            else None
        )
        try:
            result_code, state_code = _operation_state(settings, invoice_id)
        except (OSError, ValueError, ET.ParseError, urllib.error.URLError, RobokassaError) as exc:
            subscription.status_check_attempts += 1
            subscription.last_error = str(exc)[:1000]
            subscription.next_status_check_at = now + timedelta(minutes=15)
            db.commit()
            return True
        subscription.status_check_attempts += 1
        charge_started = subscription.charge_started_at or now
        if charge_started.tzinfo is None:
            charge_started = charge_started.replace(tzinfo=timezone.utc)
        final_failure = (result_code == 0 and state_code in {10, 60}) or (
            result_code == 3 and now - charge_started >= timedelta(hours=24)
        )
        if result_code == 0 and state_code == 100:
            if payment is None or checkout is None or payment.user_id is None:
                subscription.next_status_check_at = now + timedelta(minutes=15)
                subscription.last_error = "Не найдены локальные данные повторного платежа"
            else:
                user = db.get(User, payment.user_id)
                if user is None:
                    subscription.next_status_check_at = now + timedelta(minutes=15)
                    subscription.last_error = "Не найден владелец повторного платежа"
                else:
                    metadata = dict(payment.raw_payload or {})
                    payment.payment_status = "paid"
                    payment.payment_system = "robokassa"
                    payment.source_event_at = now
                    payment.paid_at = now
                    payment.raw_payload = {
                        **metadata,
                        "reconciled_via": "OpStateExt",
                        "operation_state": state_code,
                    }
                    checkout.status = "paid"
                    apply_confirmed_subscription_payment(
                        db,
                        payment,
                        user,
                        now,
                        metadata,
                        is_test_payment=False,
                    )
        elif final_failure:
            subscription.status = "cancelled" if subscription.cancelled_at else "past_due"
            subscription.next_charge_at = None
            subscription.next_status_check_at = None
            subscription.last_error = f"Robokassa state {state_code}"
            if not subscription.cancelled_at:
                subscription.failure_notification_status = "pending"
                subscription.next_notification_attempt_at = now
            if payment is not None:
                payment.payment_status = "failed"
            if checkout is not None:
                checkout.status = "failed"
        else:
            # State 5/50/80 is still in progress. State 100 waits for the signed
            # ResultUrl2, which remains the only path that extends the period.
            subscription.next_status_check_at = now + timedelta(minutes=15)
            subscription.last_error = (
                None if result_code == 0 else f"OpStateExt result {result_code}"
            )
        db.commit()
        return True


def _failed_charge_email(subscription: RecurringSubscription, settings: Settings) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Не удалось продлить сопровождение"
    sender = settings.smtp_from_email
    message["From"] = (
        f"{settings.smtp_from_name} <{sender}>" if settings.smtp_from_name else sender
    )
    message["To"] = subscription.email_normalized
    if settings.smtp_reply_to:
        message["Reply-To"] = settings.smtp_reply_to
    amount = _amount_text(subscription.amount).replace(".00", "")
    page = "https://edabalans.ru/subscription"
    text = (
        f"Не получилось списать {amount} ₽ за следующий месяц сопровождения.\n\n"
        "Новых автоматических попыток по этой карте не будет. Пополните карту и "
        "оформите подписку заново либо при новой оплате выберите другую банковскую карту:\n"
        f"{page}\n\n"
        "Если деньги всё-таки списались, не оплачивайте повторно и напишите мне:\n"
        "Telegram: https://t.me/FitnessSergey"
    )
    message.set_content(text)
    message.add_alternative(
        f"""<!doctype html><html><body style="font:16px/1.55 Arial,sans-serif;color:#172c3d">
        <div style="max-width:620px;margin:auto;padding:28px 20px">
        <h1 style="font-size:24px">Не удалось продлить сопровождение</h1>
        <p>Не получилось списать <strong>{amount} ₽</strong> за следующий месяц сопровождения.</p>
        <p>Новых автоматических попыток по этой карте не будет. Пополните карту и оформите подписку заново либо при новой оплате выберите другую банковскую карту.</p>
        <p><a href="{page}" style="display:inline-block;padding:12px 20px;border-radius:10px;background:#fb6b2b;color:#fff;text-decoration:none;font-weight:700">Открыть страницу подписки</a></p>
        <p style="color:#657984;font-size:14px">Если деньги всё-таки списались, не оплачивайте повторно и <a href="https://t.me/FitnessSergey">напишите мне</a>.</p>
        </div></body></html>""",
        subtype="html",
    )
    return message


def send_one_failure_notification(settings: Settings) -> bool:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        subscription = db.scalar(
            select(RecurringSubscription)
            .where(
                RecurringSubscription.failure_notification_status.in_(("pending", "retry")),
                RecurringSubscription.next_notification_attempt_at <= now,
            )
            .order_by(RecurringSubscription.next_notification_attempt_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if subscription is None:
            return False
        try:
            _send_message(_failed_charge_email(subscription, settings), settings)
        except Exception as exc:
            subscription.failure_notification_attempts += 1
            subscription.failure_notification_status = "retry"
            delay_hours = min(24, 2 ** min(subscription.failure_notification_attempts, 4))
            subscription.next_notification_attempt_at = now + timedelta(hours=delay_hours)
            subscription.last_error = f"notification: {exc}"[:1000]
        else:
            subscription.failure_notification_attempts += 1
            subscription.failure_notification_status = "sent"
            subscription.failure_notified_at = now
            subscription.next_notification_attempt_at = None
        db.commit()
        return True


def charge_one_due_subscription(settings: Settings) -> bool:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        subscription = db.scalar(
            select(RecurringSubscription)
            .where(
                RecurringSubscription.status == "active",
                RecurringSubscription.next_charge_at.is_not(None),
                RecurringSubscription.next_charge_at <= now,
            )
            .order_by(RecurringSubscription.next_charge_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if subscription is None:
            return False
        payment_id = uuid.uuid4()
        invoice_id = str(_invoice_id(payment_id))
        payment = Payment(
            id=payment_id,
            user_id=subscription.user_id,
            pricing_version_id=subscription.pricing_version_id,
            price_entry_code=subscription.price_entry_code,
            source=SOURCE,
            external_order_id=invoice_id,
            email_at_purchase=subscription.email_normalized,
            product_name_raw=SUBSCRIPTION_TITLE,
            amount=subscription.amount,
            amount_is_estimated=False,
            currency=subscription.currency,
            payment_status="pending",
            payment_system="robokassa",
            raw_payload={
                "test_mode": settings.robokassa_test_mode,
                "account_purchase": True,
                "success_kind": SUCCESS_KIND_SUBSCRIPTION,
                "subscription_id": str(subscription.id),
                "recurring_role": "child",
            },
        )
        checkout = OfferCheckout(
            user_id=subscription.user_id,
            checkout_kind=SUBSCRIPTION_CHECKOUT_KIND,
            pricing_version_id=subscription.pricing_version_id,
            price_entry_code=subscription.price_entry_code,
            offer_code=subscription.price_entry_code,
            title=SUBSCRIPTION_TITLE,
            items=[],
            amount=subscription.amount,
            expires_at=now + timedelta(days=1),
            payment_id=payment.id,
        )
        db.add(payment)
        db.flush()
        db.add(checkout)
        db.flush()
        payment.raw_payload = {**dict(payment.raw_payload or {}), "checkout_id": str(checkout.id)}
        subscription.status = "charging"
        subscription.pending_invoice_id = invoice_id
        subscription.charge_started_at = now
        fields = _recurring_charge_fields(settings, subscription, payment)
        try:
            request = urllib.request.Request(
                settings.robokassa_recurring_url,
                data=urllib.parse.urlencode(fields).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                answer = response.read(256).decode("utf-8", errors="replace").strip()
            if answer.casefold() != f"ok+{invoice_id}".casefold():
                raise RobokassaError(f"Robokassa не создала повторный счёт: {answer[:160]}")
            subscription.next_status_check_at = now + timedelta(minutes=5)
            db.commit()
            return True
        except (OSError, urllib.error.URLError, RobokassaError) as exc:
            # A timeout or malformed response does not prove the invoice was rejected:
            # Robokassa may have accepted it before the response was lost. Keep the
            # operation in-flight and let OpStateExt make the final decision.
            subscription.status = "charging"
            subscription.last_error = str(exc)[:1000]
            subscription.next_status_check_at = now + timedelta(minutes=5)
            db.commit()
            return True


async def recurring_subscription_worker(settings: Settings, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        processed = await asyncio.to_thread(check_one_pending_charge, settings)
        if not processed:
            processed = await asyncio.to_thread(send_one_failure_notification, settings)
        if not processed:
            processed = await asyncio.to_thread(charge_one_due_subscription, settings)
        if processed:
            continue
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.robokassa_recurring_poll_seconds
            )
        except asyncio.TimeoutError:
            pass
