from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AttributionEvent,
    MasterclassEvent,
    MasterclassNotification,
    OfferCheckout,
    Payment,
    PriceEntry,
    Product,
    ProductAccessRule,
    ProductAlias,
    Resource,
    User,
    UserAccess,
    UserEmail,
    UserOffer,
    UserPhone,
    PersonalAccessLink,
    TelegramTrackingEvent,
)
from app.access_service import complete_review, grant_resources
from app.checkout_reference import checkout_reference_from_product

MOSCOW = ZoneInfo("Europe/Moscow")
SOURCE = "tilda_webhook"
LEGACY_ALIAS_SOURCE = "google_payments_legacy"
OFFER_RESOURCES = {
    "recipes": "ACCESS_RECIPES",
    "calories": "ACCESS_CALORIES",
    "training": "ACCESS_STRENGTH",
    "recordings": "ACCESS_CONSULTATION_RECORDINGS",
    "consultation": "ACCESS_CONSULTATION",
}
OFFER_RESOURCE_COMPANIONS = {
    "ACCESS_MASTERCLASS": ("dqs",),
    "ACCESS_RECIPES": ("recipes",),
    "ACCESS_CALORIES": ("recipes", "metabolism"),
    "ACCESS_STRENGTH": ("strength",),
}


class TildaPayloadError(ValueError):
    pass


def _yclid_from_url(value: str | None) -> str | None:
    if not value:
        return None
    query = parse_qs(urlparse(value).query)
    for key, values in query.items():
        if key.lower() == "yclid" and values and values[0].strip():
            return values[0].strip()
    return None


def record_paid_tracking_event(
    db: Session,
    payment: Payment,
    referer: str | None,
    occurred_at: datetime,
) -> None:
    if payment.payment_status != "paid" or payment.user_id is None:
        return
    deduplication_key = f"metrika:purchase:{payment.id}"
    if db.scalar(select(TelegramTrackingEvent.id).where(
        TelegramTrackingEvent.deduplication_key == deduplication_key
    )):
        return

    yclid = _yclid_from_url(referer)
    source_event: TelegramTrackingEvent | None = None
    if not yclid:
        candidates = db.scalars(
            select(TelegramTrackingEvent)
            .where(
                TelegramTrackingEvent.user_id == payment.user_id,
                TelegramTrackingEvent.event_type.in_((
                    "start_first", "start_repeat", "start_maintenance"
                )),
                TelegramTrackingEvent.occurred_at <= occurred_at,
            )
            .order_by(TelegramTrackingEvent.occurred_at.desc())
        ).all()
        for candidate in candidates:
            raw_query = (candidate.metadata_json or {}).get("raw_query") or {}
            candidate_yclid = str(raw_query.get("yclid") or "").strip()
            if candidate_yclid:
                yclid = candidate_yclid
                source_event = candidate
                break

    raw_query = {"yclid": yclid} if yclid else {}
    db.add(TelegramTrackingEvent(
        id=str(uuid.uuid4()),
        tracking_link_id=source_event.tracking_link_id if source_event else None,
        user_id=payment.user_id,
        event_type="purchase_paid",
        metadata_json={
            "raw_query": raw_query,
            "payment_id": str(payment.id),
            "price": str(payment.amount),
            "currency": payment.currency,
            "attribution_source": "payment_referer" if _yclid_from_url(referer) else (
                "messenger_start" if yclid else "unattributed"
            ),
        },
        deduplication_key=deduplication_key,
        occurred_at=occurred_at,
    ))


def checkout_resource_codes(items: list[str], configured_codes: set[str]) -> list[str]:
    primary_codes = list(dict.fromkeys(
        OFFER_RESOURCES.get(item, item)
        for item in items
        if item in OFFER_RESOURCES or str(item).startswith("ACCESS_")
    ))
    if set(primary_codes) - configured_codes:
        raise TildaPayloadError("offer resources are not configured")
    candidates = list(dict.fromkeys(
        code
        for primary in primary_codes
        for code in (primary, *OFFER_RESOURCE_COMPANIONS.get(primary, ()))
    ))
    return [code for code in candidates if code in configured_codes]


def find_offer_checkout(
    db: Session, raw_product: str, user: User | None
) -> tuple[OfferCheckout | None, bool]:
    parsed_reference = checkout_reference_from_product(raw_product)
    if parsed_reference is None:
        return None, False
    reference_kind, reference = parsed_reference
    if reference_kind == "full":
        return db.get(OfferCheckout, uuid.UUID(hex=reference)), True

    candidate_scopes = []
    if user is not None:
        candidate_scopes = [
            OfferCheckout.checkout_kind == "public_site",
            OfferCheckout.user_id == user.id,
        ]
    query = select(OfferCheckout)
    if candidate_scopes:
        query = query.where(or_(*candidate_scopes))
    matches = [
        checkout
        for checkout in db.scalars(query).all()
        if checkout.id.hex.startswith(reference)
    ]
    return (matches[0] if len(matches) == 1 else None), True


def record_masterclass_purchase_event(
    db: Session,
    payment: Payment,
    occurred_at: datetime,
) -> None:
    """Emit one domain event when this payment grants masterclass ownership."""
    has_masterclass = db.scalar(
        select(UserAccess.id)
        .join(Resource, Resource.id == UserAccess.resource_id)
        .where(
            UserAccess.user_id == payment.user_id,
            Resource.code == "ACCESS_MASTERCLASS",
            UserAccess.revoked_at.is_(None),
            or_(UserAccess.expires_at.is_(None), UserAccess.expires_at > occurred_at),
        )
        .limit(1)
    )
    if not has_masterclass:
        return
    event_key = f"masterclass_purchase_confirmed:payment:{payment.id}"
    if db.scalar(select(MasterclassEvent.id).where(MasterclassEvent.event_key == event_key)):
        return
    db.add(
        MasterclassEvent(
            user_id=payment.user_id,
            event_key=event_key,
            event_type="masterclass_purchase_confirmed",
            placement=(
                "robokassa-payment" if payment.source == "robokassa" else "tilda-payment"
            ),
            occurred_at=occurred_at,
            details={"payment_id": str(payment.id)},
        )
    )


def record_offer_purchase_event_and_cancel_reminder(
    db: Session,
    payment: Payment,
    checkout: OfferCheckout | None,
    occurred_at: datetime,
) -> None:
    """Record one paid upsell and permanently close this window's sales due."""
    current_window = db.scalar(
        select(UserOffer)
        .where(
            UserOffer.user_id == payment.user_id,
            UserOffer.status == "active",
            UserOffer.started_at <= occurred_at,
            UserOffer.expires_at.is_not(None),
            UserOffer.expires_at > occurred_at,
        )
        .order_by(UserOffer.started_at.desc())
        .limit(1)
    )
    if current_window is None:
        return
    event_key = f"offer_purchase_confirmed:payment:{payment.id}"
    if not db.scalar(
        select(MasterclassEvent.id).where(MasterclassEvent.event_key == event_key)
    ):
        db.add(
            MasterclassEvent(
                user_id=payment.user_id,
                event_key=event_key,
                event_type="offer_purchase_confirmed",
                placement=(
                    "robokassa-payment" if payment.source == "robokassa" else "tilda-payment"
                ),
                occurred_at=occurred_at,
                details={
                    "payment_id": str(payment.id),
                    "checkout_id": str(checkout.id) if checkout else None,
                    "items": list(checkout.items or []) if checkout else [],
                },
            )
        )
    if current_window.trigger_event_id:
        db.execute(
            update(MasterclassNotification)
            .where(
                MasterclassNotification.user_id == payment.user_id,
                MasterclassNotification.event_id == current_window.trigger_event_id,
                MasterclassNotification.notification_kind == "sales_last_chance_due",
                MasterclassNotification.status == "pending",
            )
            .values(
                status="skipped",
                error_message="offer purchase confirmed during this window",
            )
        )


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
    *,
    source: str = SOURCE,
    verification_status: str = "tilda_unverified",
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
    return bind_user_contacts(
        db,
        user,
        email_original,
        display_name,
        phone_original,
        occurred_at,
        source=source,
        verification_status=verification_status,
    )


def bind_user_contacts(
    db: Session,
    user: User,
    email_original: str,
    display_name: str,
    phone_original: str,
    occurred_at: datetime,
    *,
    source: str = SOURCE,
    verification_status: str = "tilda_unverified",
) -> User:
    email = normalize_email(email_original)
    if email:
        email_row = validate_user_email_binding(db, user, email)
        if email_row is None:
            db.add(
                UserEmail(
                    user_id=user.id,
                    email_original=email_original,
                    email_normalized=email,
                    verification_status=verification_status,
                    source=source,
                    first_seen_at=occurred_at,
                )
            )
    if display_name and not user.display_name:
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
                    source=source,
                )
            )
    return user


def validate_user_email_binding(
    db: Session, user: User, email_original: str
) -> UserEmail | None:
    """Reject an email that cannot be safely attached to the selected user."""
    email = normalize_email(email_original)
    bound_emails = set(
        db.scalars(
            select(UserEmail.email_normalized).where(UserEmail.user_id == user.id)
        ).all()
    )
    if bound_emails and email not in bound_emails:
        raise TildaPayloadError("checkout email does not match offer recipient")
    email_row = db.scalar(select(UserEmail).where(UserEmail.email_normalized == email))
    if email_row is not None and email_row.user_id != user.id:
        raise TildaPayloadError("checkout email belongs to another user")
    return email_row


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
    if not user:
        raise TildaPayloadError("offer checkout requires an email")
    if checkout.user_id is None and checkout.checkout_kind == "public_site":
        checkout.user_id = user.id
    elif str(user.id) != str(checkout.user_id):
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
        configured_codes = set(db.scalars(
            select(Resource.code).where(Resource.status == "active")
        ))
        resource_codes = checkout_resource_codes(list(checkout.items), configured_codes)
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
            record_masterclass_purchase_event(db, payment, occurred_at)
            return True
        resources = {
            row.code: row
            for row in db.scalars(
                select(Resource).where(Resource.code.in_(resource_codes))
            )
        }
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
    if checkout is not None or access_granted:
        record_offer_purchase_event_and_cancel_reminder(
            db, payment, checkout, occurred_at
        )
    if access_granted:
        record_masterclass_purchase_event(db, payment, occurred_at)
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
    checkout, has_checkout_reference = find_offer_checkout(db, raw_product, None)
    if has_checkout_reference:
        if checkout is None:
            raise TildaPayloadError("offer checkout is unknown")
    if checkout is not None and checkout.user_id is not None:
        user = db.get(User, checkout.user_id)
        if user is None:
            raise TildaPayloadError("offer checkout user is missing")
        user = bind_user_contacts(
            db, user, email, display_name, phone, event_at
        )
    else:
        user = find_or_create_user(db, email, display_name, phone, event_at)
    product = find_product(db, raw_product)
    if not has_checkout_reference:
        checkout, has_checkout_reference = find_offer_checkout(db, raw_product, user)
    if has_checkout_reference:
        if checkout is None:
            raise TildaPayloadError("offer checkout is unknown")
        if checkout.pricing_version_id and checkout.price_entry_code:
            price_entry = db.scalar(
                select(PriceEntry).where(
                    PriceEntry.version_id == checkout.pricing_version_id,
                    PriceEntry.code == checkout.price_entry_code,
                )
            )
            if price_entry is None:
                raise TildaPayloadError("checkout pricing snapshot is missing")
            if price_entry.product_code:
                product = db.scalar(
                    select(Product).where(Product.code == price_entry.product_code)
                )
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
        existing.pricing_version_id = existing.pricing_version_id or (
            checkout.pricing_version_id if checkout else None
        )
        existing.price_entry_code = existing.price_entry_code or (
            checkout.price_entry_code if checkout else None
        )
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
        record_paid_tracking_event(db, existing, referer, event_at)
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
        pricing_version_id=checkout.pricing_version_id if checkout else None,
        price_entry_code=checkout.price_entry_code if checkout else None,
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
    record_paid_tracking_event(db, payment, referer, event_at)

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
