from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from urllib.parse import quote_plus
import uuid
from zoneinfo import ZoneInfo

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.intensive_web_access import OFFER_CODE, OFFER_DISCOUNT, offer_for_user
from app.models import OfferCheckout, Payment, PriceEntry, PricingVersion, Product, User
from app.pricing_service import amount_value, pricing_entry_map, site_tariff_amount
from app.product_catalog_service import tariff_public
from app.tilda_service import (
    TildaPayloadError,
    bind_user_contacts,
    find_or_create_user,
    grant_payment_access,
    validate_user_email_binding,
)
from app.account_onboarding_service import ensure_paid_account_onboarding


SOURCE = "robokassa"
MOSCOW = ZoneInfo("Europe/Moscow")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
HASH_ALGORITHMS = {"md5", "sha1", "sha256", "sha384", "sha512"}


class RobokassaError(ValueError):
    pass


def normalize_checkout_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
        raise RobokassaError("Укажите корректный email")
    return email


def _encoded(value: str) -> str:
    return quote_plus(value, safe="")


def _amount_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _invoice_id(payment_id: uuid.UUID) -> int:
    return (payment_id.int & ((1 << 63) - 1)) or 1


def _require_checkout_settings(settings: Settings) -> tuple[str, str]:
    if not settings.robokassa_checkout_enabled:
        raise RobokassaError("Прямая тестовая оплата пока выключена")
    merchant = settings.robokassa_merchant_login.strip()
    password = (
        settings.robokassa_test_password_1
        if settings.robokassa_test_mode
        else settings.robokassa_password_1
    )
    algorithm = settings.robokassa_hash_algorithm.strip().lower()
    if not merchant or not password:
        raise RobokassaError("Не заполнены реквизиты магазина Robokassa")
    if algorithm not in HASH_ALGORITHMS:
        raise RobokassaError("Не поддерживается алгоритм подписи Robokassa")
    if not settings.robokassa_receipt_tax.strip():
        raise RobokassaError("Не заполнена ставка налога для чека Robokassa")
    _result_public_key(settings)
    return merchant, password


def _result_public_key(settings: Settings) -> rsa.RSAPublicKey:
    try:
        certificate_bytes = base64.b64decode(
            settings.robokassa_jws_certificate_base64, validate=True
        )
        if certificate_bytes.lstrip().startswith(b"-----BEGIN CERTIFICATE-----"):
            certificate = x509.load_pem_x509_certificate(certificate_bytes)
        else:
            certificate = x509.load_der_x509_certificate(certificate_bytes)
    except (ValueError, TypeError) as exc:
        raise RobokassaError("Не настроен сертификат ResultUrl2") from exc
    public_key = certificate.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise RobokassaError("Сертификат ResultUrl2 не содержит RSA-ключ")
    return public_key


def _receipt(settings: Settings, title: str, amount: Decimal) -> str:
    item = {
        "name": title[:128],
        "quantity": 1,
        "sum": amount_value(amount),
        "tax": settings.robokassa_receipt_tax.strip(),
        "payment_method": settings.robokassa_receipt_payment_method.strip(),
        "payment_object": settings.robokassa_receipt_payment_object.strip(),
    }
    receipt: dict[str, object] = {"items": [item]}
    if settings.robokassa_receipt_sno.strip():
        receipt["sno"] = settings.robokassa_receipt_sno.strip()
    return json.dumps(receipt, ensure_ascii=False, separators=(",", ":"))


def _payment_fields(
    settings: Settings,
    payment: Payment,
    title: str,
    email: str,
    expires_at: datetime,
) -> dict[str, str]:
    merchant, password = _require_checkout_settings(settings)
    if payment.amount is None or payment.external_order_id is None:
        raise RobokassaError("Заказ Robokassa сформирован не полностью")
    receipt = _encoded(_receipt(settings, title, payment.amount))
    values = [
        merchant,
        _amount_text(payment.amount),
        payment.external_order_id,
        receipt,
        settings.robokassa_result_url_2,
        settings.robokassa_success_url_2,
        "GET",
        settings.robokassa_fail_url_2,
        "GET",
        password,
    ]
    signature = hashlib.new(
        settings.robokassa_hash_algorithm.strip().lower(), ":".join(values).encode("utf-8")
    ).hexdigest()
    return {
        "MerchantLogin": merchant,
        "OutSum": _amount_text(payment.amount),
        "InvId": payment.external_order_id,
        "Description": title[:100],
        "Email": email,
        "Culture": "ru",
        "Encoding": "utf-8",
        "ExpirationDate": expires_at.astimezone(MOSCOW).strftime("%Y-%m-%dT%H:%M"),
        # Robokassa signs and receives Receipt as URL-encoded JSON. The outer
        # form/query transport therefore encodes the percent signs once more.
        "Receipt": receipt,
        "ResultUrl2": settings.robokassa_result_url_2,
        "SuccessUrl2": settings.robokassa_success_url_2,
        "SuccessUrl2Method": "GET",
        "FailUrl2": settings.robokassa_fail_url_2,
        "FailUrl2Method": "GET",
        "SignatureValue": signature,
        "IsTest": "1" if settings.robokassa_test_mode else "0",
    }


def create_payment(
    db: Session,
    settings: Settings,
    version: PricingVersion,
    price_code: str,
    email_original: str,
    *,
    offer_user_id: uuid.UUID | None = None,
) -> dict:
    _require_checkout_settings(settings)
    email = normalize_checkout_email(email_original)
    if offer_user_id is not None:
        offer_user = db.get(User, offer_user_id)
        if offer_user is None:
            raise RobokassaError("Получатель скидки не найден")
        try:
            validate_user_email_binding(db, offer_user, email)
        except TildaPayloadError as exc:
            raise RobokassaError(str(exc)) from exc
    entry = pricing_entry_map(db, version).get(price_code)
    if entry is None or entry.section != "site_tariffs" or not entry.enabled:
        raise RobokassaError("Тариф недоступен")
    catalog_tariff = tariff_public(db, entry.product_code or "")
    title = catalog_tariff["name"] if catalog_tariff else entry.name
    now = datetime.now(timezone.utc)
    offer = offer_for_user(db, offer_user_id) if offer_user_id else None
    amount = site_tariff_amount(
        entry,
        personal_discount=Decimal(OFFER_DISCOUNT) if offer else Decimal("0"),
    )
    expires_at = now + timedelta(hours=2)
    if offer and offer.expires_at:
        offer_expires_at = offer.expires_at
        if offer_expires_at.tzinfo is None:
            offer_expires_at = offer_expires_at.replace(tzinfo=timezone.utc)
        expires_at = min(expires_at, offer_expires_at)
    payment_id = uuid.uuid4()
    invoice_id = str(_invoice_id(payment_id))
    product = db.scalar(select(Product).where(Product.code == entry.product_code))
    payment = Payment(
        id=payment_id,
        product_id=product.id if product else None,
        pricing_version_id=version.id,
        price_entry_code=entry.code,
        source=SOURCE,
        external_order_id=invoice_id,
        email_at_purchase=email,
        product_name_raw=title,
        amount=amount,
        amount_is_estimated=False,
        currency=entry.currency,
        payment_status="pending",
        payment_system="robokassa",
        raw_payload={"test_mode": settings.robokassa_test_mode},
    )
    checkout = OfferCheckout(
        user_id=offer_user_id,
        checkout_kind="public_site_robokassa",
        pricing_version_id=version.id,
        price_entry_code=entry.code,
        offer_code=entry.code,
        title=title,
        items=list(entry.resource_codes or []),
        amount=amount,
        expires_at=expires_at,
        payment_id=payment.id,
    )
    # These models intentionally do not expose an ORM relationship. Flush the
    # referenced payment first so PostgreSQL can satisfy the checkout FK.
    db.add(payment)
    db.flush()
    db.add(checkout)
    db.flush()
    payment.raw_payload = {
        "test_mode": settings.robokassa_test_mode,
        "checkout_id": str(checkout.id),
        "offer_code": OFFER_CODE if offer else None,
    }
    fields = _payment_fields(settings, payment, title, email, expires_at)
    db.commit()
    return {
        "ok": True,
        "invoice_id": invoice_id,
        "amount": amount_value(amount),
        "price_code": entry.code,
        "pricing_version": version.version_number,
        "intensive_offer": OFFER_CODE if offer else None,
        "test_mode": settings.robokassa_test_mode,
        "expires_at": expires_at.isoformat(),
        "payment_form": {
            "action": settings.robokassa_payment_url,
            "method": "POST",
            "fields": fields,
        },
    }


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_result2(settings: Settings, compact_jws: str) -> dict:
    parts = compact_jws.strip().split(".")
    if len(parts) != 3:
        raise RobokassaError("Некорректный формат ResultUrl2")
    try:
        header = json.loads(_b64url_decode(parts[0]))
        payload = json.loads(_b64url_decode(parts[1]))
        signature = _b64url_decode(parts[2])
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RobokassaError("Не удалось прочитать подпись ResultUrl2") from exc
    if header.get("alg") != "RS256":
        raise RobokassaError("Недопустимый алгоритм ResultUrl2")
    public_key = _result_public_key(settings)
    try:
        public_key.verify(
            signature,
            f"{parts[0]}.{parts[1]}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise RobokassaError("Подпись ResultUrl2 не совпала") from exc
    if payload.get("header", {}).get("type") != "PaymentStateNotification":
        raise RobokassaError("Неизвестный тип ResultUrl2")
    return payload


def confirm_payment(db: Session, settings: Settings, compact_jws: str) -> str:
    payload = verify_result2(settings, compact_jws)
    data = payload.get("data") or {}
    invoice_id = str(data.get("invId") or "")
    operation_id = str(data.get("opKey") or "")
    if data.get("shop") != settings.robokassa_merchant_login.strip():
        raise RobokassaError("ResultUrl2 пришёл от другого магазина")
    if data.get("state") != "OK" or not invoice_id or not operation_id:
        raise RobokassaError("Robokassa не подтвердила оплату")
    payment = db.scalar(
        select(Payment).where(
            Payment.source == SOURCE,
            Payment.external_order_id == invoice_id,
        ).with_for_update()
    )
    if payment is None:
        raise RobokassaError("Счёт Robokassa не найден")
    if payment.payment_status in {"paid", "test_paid"}:
        if payment.external_payment_id != operation_id:
            raise RobokassaError("Операция Robokassa не совпадает со счётом")
        db.rollback()
        return invoice_id
    try:
        paid_amount = Decimal(str(data.get("incSum")))
    except (InvalidOperation, TypeError) as exc:
        raise RobokassaError("Некорректная сумма ResultUrl2") from exc
    if payment.amount is None or paid_amount != payment.amount:
        raise RobokassaError("Сумма ResultUrl2 не совпадает со счётом")
    checkout = db.scalar(
        select(OfferCheckout).where(OfferCheckout.payment_id == payment.id)
    )
    if checkout is None:
        raise RobokassaError("Checkout Robokassa не найден")
    timestamp = payload.get("header", {}).get("timestamp")
    try:
        occurred_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        occurred_at = datetime.now(timezone.utc)
    if checkout.user_id is not None:
        user = db.get(User, checkout.user_id)
        if user is None:
            raise RobokassaError("Получатель скидки не найден")
        try:
            user = bind_user_contacts(
                db,
                user,
                payment.email_at_purchase or "",
                "",
                "",
                occurred_at,
                source=SOURCE,
                verification_status="payment_unverified",
            )
        except TildaPayloadError as exc:
            raise RobokassaError(str(exc)) from exc
    else:
        try:
            user = find_or_create_user(
                db,
                payment.email_at_purchase or "",
                "",
                "",
                occurred_at,
                source=SOURCE,
                verification_status="payment_unverified",
            )
        except TildaPayloadError as exc:
            raise RobokassaError(str(exc)) from exc
    if user is None:
        raise RobokassaError("В счёте отсутствует email")
    is_test_payment = bool((payment.raw_payload or {}).get("test_mode"))
    payment.user_id = user.id
    payment.external_payment_id = operation_id
    payment.payment_status = "test_paid" if is_test_payment else "paid"
    payment.payment_system = str(data.get("paymentMethod") or "robokassa")[:64]
    payment.source_event_at = occurred_at
    payment.paid_at = occurred_at
    payment.raw_payload = {
        "integration": {"test_mode": is_test_payment},
        "notification": payload,
    }
    checkout.user_id = user.id
    checkout.status = payment.payment_status
    if not is_test_payment:
        grant_payment_access(db, payment, checkout, occurred_at)
        if settings.account_onboarding_enabled:
            ensure_paid_account_onboarding(db, payment, settings)
    db.commit()
    return invoice_id
