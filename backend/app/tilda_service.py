from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AttributionEvent,
    OfferCheckout,
    Payment,
    Product,
    ProductAccessRule,
    ProductAlias,
    Resource,
    User,
    UserAccess,
    UserEmail,
    UserPhone,
    PersonalAccessLink,
)
from app.access_service import complete_review, grant_resources

MOSCOW = ZoneInfo("Europe/Moscow")
SOURCE = "tilda_webhook"
LEGACY_ALIAS_SOURCE = "google_payments_legacy"
OFFER_CODE = re.compile(r"^EB-([0-9a-fA-F]{32})(?:\s|$)")
OFFER_RESOURCES = {
    "recipes": "ACCESS_RECIPES",
    "calories": "ACCESS_CALORIES",
    "training": "ACCESS_STRENGTH",
    "recordings": "ACCESS_CONSULTATION_RECORDINGS",
    "consultation": "ACCESS_CONSULTATION",
}


class TildaPayloadError(ValueError):
    pass


def clean(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def first(payload: dict[str, Any], *names: str) -> str:
    for name in names:
        value = clean(payload.get(name))
        if value:
            return value
    return ""


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_phone(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return f"+{digits}" if digits else ""


def parse_amount(value: str) -> Decimal:
    raw = value.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise TildaPayloadError("price is missing or invalid") from exc
    if amount < 0:
        raise TildaPayloadError("price cannot be negative")
    return amount


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    for pattern in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=MOSCOW)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=MOSCOW)
    except ValueError:
        return None


def normalize_status(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"paid", "success", "succeeded", "оплачен", "оплачено"}:
        return "paid"
    if normalized in {"processing", "pending", "в процессе", "ожидает оплаты"}:
        return "processing"
    return normalized or "unknown"


def normalize_currency(value: str) -> str:
    normalized = value.strip().upper()
    if normalized in {"", "RUR", "РУБ", "РУБ."}:
        return "RUB"
    if len(normalized) != 3:
        raise TildaPayloadError("currency must contain a three-letter code")
    return normalized


def find_existing_payment(
    db: Session, external_order_id: str | None, external_payment_id: str | None
) -> Payment | None:
    conditions = []
    if external_order_id:
        conditions.append(Payment.external_order_id == external_order_id)
    if external_payment_id:
        conditions.append(Payment.external_payment_id == external_payment_id)
    if not conditions:
        return None
    return db.scalar(
        select(Payment).where(Payment.source == SOURCE, or_(*conditions))
    )


def find_or_create_user(
    db: Session,
    email_original: str,
    display_name: str,
    phone_original: str,
    occurred_at: datetime,
) -> User | None:
    email = normalize_email(email_original)
    if not email:
        return None
    user = db.scalar(
        select(User)
        .join(UserEmail, UserEmail.user_id == User.id)
        .where(UserEmail.email_normalized == email, User.merged_into_user_id.is_(None))
    )
    if user is None:
        user = User(
            display_name=display_name or None,
            data_origin="native",
            first_seen_at=occurred_at,
        )
        db.add(user)
        db.flush()
        db.add(
            UserEmail(
                user_id=user.id,
                email_original=email_original,
                email_normalized=email,
                verification_status="tilda_unverified",
                source=SOURCE,
                first_seen_at=occurred_at,
            )
        )
    elif display_name and not user.display_name:
        user.display_name = display_name

    normalized_phone = normalize_phone(phone_original)
    if normalized_phone:
        phone_exists = db.scalar(
            select(UserPhone.id).where(
                UserPhone.user_id == user.id,
                UserPhone.phone_normalized == normalized_phone,
            )
        )
        if phone_exists is None:
            db.add(
                UserPhone(
                    user_id=user.id,
                    phone_original=phone_original,
                    phone_normalized=normalized_phone,
                    source=SOURCE,
                )
            )
    return user


def find_product(db: Session, raw_name: str) -> Product | None:
    for source in (SOURCE, LEGACY_ALIAS_SOURCE):
        product = db.scalar(
            select(Product)
            .join(ProductAlias, ProductAlias.product_id == Product.id)
            .where(
                ProductAlias.source == source,
                ProductAlias.raw_name_exact == raw_name,
                Product.status == "active",
            )
        )
        if product is not None:
            return product
    return None


def active_access_rules(
    db: Session, product_id: Any, occurred_at: datetime
) -> list[ProductAccessRule]:
    return list(
        db.scalars(
            select(ProductAccessRule).where(
                ProductAccessRule.product_id == product_id,
                or_(
                    ProductAccessRule.effective_from.is_(None),
                    ProductAccessRule.effective_from <= occurred_at,
                ),
                or_(
                    ProductAccessRule.effective_to.is_(None),
                    ProductAccessRule.effective_to > occurred_at,
                ),
            )
        )
    )


def attribution_from_url(url: str) -> dict[str, str | None]:
    query = parse_qs(urlparse(url).query)
    return {
        "utm_source": query.get("utm_source", [None])[0],
        "utm_medium": query.get("utm_medium", [None])[0],
        "utm_campaign": query.get("utm_campaign", [None])[0],
        "utm_content": query.get("utm_content", [None])[0],
        "utm_term": query.get("utm_term", [None])[0],
        "ref_code": query.get("ref", query.get("invite", [None]))[0],
    }


def validate_checkout(
    checkout: OfferCheckout,
    user: User | None,
    amount: Decimal,
    event_at: datetime,
    *,
    existing_payment: Payment | None = None,
) -> None:
    checkout_expires = checkout.expires_at
    if checkout_expires.tzinfo is None:
        checkout_expires = checkout_expires.replace(tzinfo=timezone.utc)
    is_linked_payment = (
        existing_payment is not None and checkout.payment_id == existing_payment.id
    )
    if not is_linked_payment and (
        checkout.status != "pending"
        or checkout_expires < event_at.astimezone(timezone.utc)
    ):
        raise TildaPayloadError("offer checkout is expired or already used")
    if not user or str(user.id) != str(checkout.user_id):
        raise TildaPayloadError("offer checkout belongs to another email")
    if amount != checkout.amount:
        raise TildaPayloadError("offer checkout price does not match")


def grant_payment_access(
    db: Session,
    payment: Payment,
    checkout: OfferCheckout | None,
    occurred_at: datetime,
) -> bool:
    if payment.user_id is None or payment.payment_status != "paid":
        return False

    resource_sources: list[tuple[Any, str]] = []
    if checkout is not None:
        resource_codes = list(dict.fromkeys(
            OFFER_RESOURCES.get(item, item)
            for item in checkout.items
            if item in OFFER_RESOURCES or str(item).startswith("ACCESS_")
        ))
        personal_link = db.scalar(
            select(PersonalAccessLink).where(PersonalAccessLink.checkout_id == checkout.id)
        )
        if personal_link is not None:
            user = db.get(User, payment.user_id)
            if user is None:
                raise TildaPayloadError("personal offer user is missing")
            grant_resources(
                db,
                user,
                resource_codes,
                source="paid_personal_link",
                source_payment_id=payment.id,
                unlock_modes=dict(personal_link.unlock_modes or {}),
            )
            personal_link.status = "paid"
            personal_link.resolved_at = occurred_at
            complete_review(user, "Права подтверждены оплатой персонального предложения Сергея")
            return True
        resources = {
            row.code: row
            for row in db.scalars(
                select(Resource).where(Resource.code.in_(resource_codes))
            )
        }
        if set(resource_codes) - set(resources):
            raise TildaPayloadError("offer resources are not configured")
        resource_sources = [
            (resources[code].id, "paid_offer_checkout") for code in resource_codes
        ]
    elif payment.product_id is not None:
        resource_sources = [
            (rule.resource_id, "paid_product_rule")
            for rule in active_access_rules(db, payment.product_id, occurred_at)
        ]

    access_granted = False
    for resource_id, source in resource_sources:
        already_granted = db.scalar(
            select(UserAccess.id).where(
                UserAccess.user_id == payment.user_id,
                UserAccess.resource_id == resource_id,
                UserAccess.source_payment_id == payment.id,
            )
        )
        if already_granted is not None:
            continue
        db.add(
            UserAccess(
                user_id=payment.user_id,
                resource_id=resource_id,
                source_payment_id=payment.id,
                source=source,
                granted_at=occurred_at,
            )
        )
        access_granted = True
    return access_granted


def process_tilda_payment(db: Session, payload: dict[str, Any]) -> dict[str, str]:
    external_order_id = first(payload, "orderid", "order_id") or None
    external_payment_id = first(payload, "paymentid", "payment_id") or None
    if not external_order_id and not external_payment_id:
        raise TildaPayloadError("orderid or paymentid is required")

    raw_product = first(payload, "products", "Products", "product")
    if not raw_product:
        raise TildaPayloadError("products is required")
    amount = parse_amount(first(payload, "price", "amount", "Amount"))
    event_at = parse_datetime(first(payload, "sent", "Sent")) or datetime.now(MOSCOW)
    payment_status = normalize_status(
        first(payload, "Payment status", "Статус оплаты", "payment_status")
    )
    email = first(payload, "Email", "email", "ma_email")
    display_name = first(payload, "Name", "name", "ma_name")
    phone = first(payload, "Phone", "phone", "ma_phone")
    user = find_or_create_user(db, email, display_name, phone, event_at)
    product = find_product(db, raw_product)
    checkout_match = OFFER_CODE.match(raw_product)
    checkout = db.get(OfferCheckout, uuid.UUID(hex=checkout_match.group(1))) if checkout_match else None
    if checkout_match:
        if checkout is None:
            raise TildaPayloadError("offer checkout is unknown")
    referer = first(payload, "referer", "Referer")

    existing = find_existing_payment(db, external_order_id, external_payment_id)
    if existing is not None:
        if payment_status != "paid" or existing.payment_status == "paid":
            db.rollback()
            return {"status": "duplicate", "payment_id": str(existing.id)}
        if (
            existing.external_order_id
            and external_order_id
            and existing.external_order_id != external_order_id
        ) or (
            existing.external_payment_id
            and external_payment_id
            and existing.external_payment_id != external_payment_id
        ):
            raise TildaPayloadError("payment update identifiers do not match")
        if existing.product_name_raw != raw_product or existing.amount != amount:
            raise TildaPayloadError("payment update does not match the original order")
        if user is None and existing.user_id is not None:
            user = db.get(User, existing.user_id)
        if user is not None and existing.user_id is not None and user.id != existing.user_id:
            raise TildaPayloadError("payment update belongs to another email")
        linked_checkout = db.scalar(
            select(OfferCheckout).where(OfferCheckout.payment_id == existing.id)
        )
        if (
            checkout is not None
            and linked_checkout is not None
            and checkout.id != linked_checkout.id
        ):
            raise TildaPayloadError("payment update belongs to another offer checkout")
        checkout = checkout or linked_checkout
        if checkout is not None:
            validate_checkout(
                checkout,
                user,
                amount,
                event_at,
                existing_payment=existing,
            )

        existing.user_id = existing.user_id or (user.id if user else None)
        existing.product_id = existing.product_id or (product.id if product else None)
        existing.external_order_id = existing.external_order_id or external_order_id
        existing.external_payment_id = (
            existing.external_payment_id or external_payment_id
        )
        existing.payment_status = "paid"
        existing.paid_at = event_at
        existing.paid_at_is_estimated = True
        existing.source_event_at = event_at
        existing.raw_payload = payload
        existing.external_request_id = (
            first(payload, "requestid", "tranid") or existing.external_request_id
        )
        if checkout is not None:
            checkout.status = "paid"
        access_granted = grant_payment_access(db, existing, checkout, event_at)
        if existing.user_id is not None and referer:
            db.add(
                AttributionEvent(
                    user_id=existing.user_id,
                    event_type="tilda_paid_order",
                    landing_url=referer,
                    occurred_at=event_at,
                    **attribution_from_url(referer),
                )
            )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return {"status": "duplicate", "payment_id": str(existing.id)}
        return {
            "status": "updated_to_paid",
            "payment_id": str(existing.id),
            "access": "granted" if access_granted else "not_granted",
        }

    if checkout is not None:
        validate_checkout(checkout, user, amount, event_at)

    payment = Payment(
        user_id=user.id if user else None,
        product_id=product.id if product else None,
        source=SOURCE,
        external_order_id=external_order_id,
        external_payment_id=external_payment_id,
        external_request_id=first(payload, "requestid", "tranid") or None,
        email_at_purchase=email or None,
        product_name_raw=raw_product,
        amount=amount,
        currency=normalize_currency(
            first(payload, "Currency", "Валюта", "currency")
        ),
        payment_status=payment_status,
        payment_system=first(payload, "paymentsystem", "payment_system") or None,
        source_event_at=event_at,
        paid_at=event_at if payment_status == "paid" else None,
        paid_at_is_estimated=payment_status == "paid",
        external_form_id=first(payload, "formid", "form_id") or None,
        form_name_raw=first(
            payload, "Form name", "Название формы", "formname"
        )
        or None,
        referer_raw=referer or None,
        landing_url=referer or None,
        raw_payload=payload,
    )
    db.add(payment)
    db.flush()
    if checkout:
        checkout.payment_id = payment.id
        checkout.status = "paid" if payment_status == "paid" else payment_status

    if user and referer and payment_status == "paid":
        db.add(
            AttributionEvent(
                user_id=user.id,
                event_type="tilda_paid_order",
                landing_url=referer,
                occurred_at=event_at,
                **attribution_from_url(referer),
            )
        )

    access_granted = grant_payment_access(db, payment, checkout, event_at)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = find_existing_payment(db, external_order_id, external_payment_id)
        if existing is None:
            raise
        return {"status": "duplicate", "payment_id": str(existing.id)}

    result_status = "saved"
    if product is None and checkout is None:
        result_status = "saved_unmapped_product"
    elif payment_status != "paid":
        result_status = "saved_without_access"
    return {
        "status": result_status,
        "payment_id": str(payment.id),
        "access": "granted" if access_granted else "not_granted",
    }
