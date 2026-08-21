from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AttributionEvent,
    ImportBatch,
    LegacyImportRecord,
    MessengerAccount,
    Payment,
    Product,
    ProductAccessRule,
    ProductAlias,
    Resource,
    User,
    UserAccess,
    UserEmail,
)

MOSCOW = ZoneInfo("Europe/Moscow")
SOURCE_PAYMENTS = "google_payments_legacy"
SOURCE_CLIENTS = "google_clients_legacy"

PRODUCTS = {
    "MASTERCLASS_BASIC": "Мастер-класс",
    "MASTERCLASS_RECIPES": "Мастер-класс + рецепты",
    "MASTERCLASS_CONSULT": "Мастер-класс + рецепты + консультация",
    "RECIPES_ADDON": "Каталог рецептов",
    "CONSULTATION": "Консультация",
    "COACHING": "Сопровождение",
    "CALORIES_COURSE": "Курс о калориях",
    "TRAINING_COURSE": "Курс по тренировкам",
}

RESOURCES = {
    "ACCESS_MASTERCLASS": "Мастер-класс",
    "ACCESS_RECIPES": "Рецепты",
    "ACCESS_CONSULTATION": "Консультация",
    "ACCESS_COACHING": "Сопровождение",
    "ACCESS_CALORIES": "Курс о калориях",
    "ACCESS_STRENGTH": "Приложение тренировок",
}

BASE_RULES = {
    "MASTERCLASS_BASIC": ["ACCESS_MASTERCLASS"],
    "MASTERCLASS_RECIPES": ["ACCESS_MASTERCLASS", "ACCESS_RECIPES"],
    "MASTERCLASS_CONSULT": [
        "ACCESS_MASTERCLASS",
        "ACCESS_RECIPES",
        "ACCESS_CONSULTATION",
    ],
    "RECIPES_ADDON": ["ACCESS_RECIPES"],
    "CONSULTATION": ["ACCESS_CONSULTATION"],
    "COACHING": ["ACCESS_COACHING"],
    "CALORIES_COURSE": ["ACCESS_CALORIES"],
    "TRAINING_COURSE": ["ACCESS_STRENGTH"],
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_email(value: Any) -> str:
    return clean(value).lower()


def normalize_username(value: Any) -> str:
    return clean(value).lstrip("@").strip()


def parse_datetime(value: Any) -> datetime | None:
    raw = clean(value)
    if not raw:
        return None
    candidates = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%d.%m.%y",
    )
    for pattern in candidates:
        try:
            return datetime.strptime(raw, pattern).replace(tzinfo=MOSCOW)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=MOSCOW)
    except ValueError:
        return None


def parse_amount(value: Any) -> Decimal:
    raw = clean(value).replace(" ", "").replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {value!r}") from exc


def row_payload(headers: list[Any], row: list[Any]) -> dict[str, Any]:
    return {
        clean(header) or f"unnamed_{index + 1}": row[index] if index < len(row) else None
        for index, header in enumerate(headers)
    }


def payload_hash(source: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(f"{source}\n{canonical}".encode()).hexdigest()


def first(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if clean(payload.get(name)):
            return payload[name]
    return None


def normalize_payment_status(payload: dict[str, Any]) -> str:
    raw = clean(first(payload, "Payment status", "Статус оплаты")).lower()
    if raw in {"paid", "оплачено"}:
        return "paid"
    if raw in {"в процессе", "processing", "pending"}:
        return "processing"
    return raw or "unknown"


def find_user_by_email(db: Session, email: str) -> User | None:
    if not email:
        return None
    return db.scalar(
        select(User)
        .join(UserEmail, UserEmail.user_id == User.id)
        .where(UserEmail.email_normalized == email, User.merged_into_user_id.is_(None))
    )


def find_user_by_messenger(
    db: Session, platform: str, platform_user_id: str
) -> User | None:
    if not platform_user_id:
        return None
    return db.scalar(
        select(User)
        .join(MessengerAccount, MessengerAccount.user_id == User.id)
        .where(
            MessengerAccount.platform == platform,
            MessengerAccount.platform_user_id == platform_user_id,
            User.merged_into_user_id.is_(None),
        )
    )


def make_user(
    db: Session, display_name: str, first_seen_at: datetime | None
) -> User:
    user = User(
        display_name=display_name or None,
        first_seen_at=first_seen_at,
        data_origin="legacy_import",
    )
    db.add(user)
    db.flush()
    return user


def attach_email(
    db: Session,
    user: User,
    email_original: str,
    source: str,
    first_seen_at: datetime | None,
) -> None:
    normalized = normalize_email(email_original)
    if not normalized:
        return
    existing = db.scalar(select(UserEmail).where(UserEmail.email_normalized == normalized))
    if existing:
        return
    db.add(
        UserEmail(
            user_id=user.id,
            email_original=clean(email_original),
            email_normalized=normalized,
            source=source,
            first_seen_at=first_seen_at,
        )
    )


def attach_or_update_messenger(
    db: Session,
    user: User,
    platform: str,
    platform_user_id: str,
    username: str,
    first_name: str,
    first_seen_at: datetime | None,
) -> None:
    account = None
    if platform_user_id:
        account = db.scalar(
            select(MessengerAccount).where(
                MessengerAccount.platform == platform,
                MessengerAccount.platform_user_id == platform_user_id,
            )
        )
    if account:
        if username:
            account.username = username
        if first_name:
            account.first_name = first_name
        if first_seen_at and (
            account.first_seen_at is None or first_seen_at < account.first_seen_at
        ):
            account.first_seen_at = first_seen_at
        if first_seen_at and (
            account.last_seen_at is None or first_seen_at > account.last_seen_at
        ):
            account.last_seen_at = first_seen_at
        return
    db.add(
        MessengerAccount(
            user_id=user.id,
            platform=platform,
            platform_user_id=platform_user_id or None,
            username=username or None,
            first_name=first_name or None,
            first_seen_at=first_seen_at,
            last_seen_at=first_seen_at,
            linked_at=first_seen_at if platform_user_id else None,
            source=SOURCE_CLIENTS,
        )
    )


def seed_catalog(
    db: Session, aliases: dict[str, str], standard_calories_cutoff: datetime
) -> tuple[dict[str, Product], dict[str, Resource]]:
    products: dict[str, Product] = {}
    for code, name in PRODUCTS.items():
        product = db.scalar(select(Product).where(Product.code == code))
        if product is None:
            product = Product(code=code, name=name)
            db.add(product)
            db.flush()
        products[code] = product

    resources: dict[str, Resource] = {}
    for code, name in RESOURCES.items():
        resource = db.scalar(select(Resource).where(Resource.code == code))
        if resource is None:
            resource = Resource(code=code, name=name)
            db.add(resource)
            db.flush()
        resources[code] = resource

    for product_code, resource_codes in BASE_RULES.items():
        for resource_code in resource_codes:
            exists = db.scalar(
                select(ProductAccessRule.id).where(
                    ProductAccessRule.product_id == products[product_code].id,
                    ProductAccessRule.resource_id == resources[resource_code].id,
                    ProductAccessRule.effective_from.is_(None),
                    ProductAccessRule.effective_to.is_(None),
                )
            )
            if not exists:
                db.add(
                    ProductAccessRule(
                        product_id=products[product_code].id,
                        resource_id=resources[resource_code].id,
                    )
                )

    calories_rule = db.scalar(
        select(ProductAccessRule.id).where(
            ProductAccessRule.product_id == products["MASTERCLASS_RECIPES"].id,
            ProductAccessRule.resource_id == resources["ACCESS_CALORIES"].id,
            ProductAccessRule.effective_to == standard_calories_cutoff,
        )
    )
    if not calories_rule:
        db.add(
            ProductAccessRule(
                product_id=products["MASTERCLASS_RECIPES"].id,
                resource_id=resources["ACCESS_CALORIES"].id,
                effective_to=standard_calories_cutoff,
            )
        )

    for raw_name, product_code in aliases.items():
        if product_code not in products:
            raise ValueError(f"unknown product code for alias: {product_code}")
        existing = db.scalar(
            select(ProductAlias).where(
                ProductAlias.source == SOURCE_PAYMENTS,
                ProductAlias.raw_name_exact == raw_name,
            )
        )
        if existing is None:
            db.add(
                ProductAlias(
                    product_id=products[product_code].id,
                    source=SOURCE_PAYMENTS,
                    raw_name_exact=raw_name,
                )
            )
    db.flush()
    return products, resources


def add_import_record(
    db: Session,
    batch: ImportBatch,
    source: str,
    row_number: int,
    row_hash: str,
    payload: dict[str, Any],
    status: str,
    user: User | None = None,
    payment: Payment | None = None,
    reason: str | None = None,
) -> None:
    db.add(
        LegacyImportRecord(
            import_batch_id=batch.id,
            source=source,
            source_row_number=row_number,
            row_hash=row_hash,
            external_record_id=clean(payload.get("Доступ_МК_Качество")) or None,
            status=status,
            user_id=user.id if user else None,
            payment_id=payment.id if payment else None,
            reason=reason,
            raw_payload=payload,
        )
    )


def already_imported(db: Session, source: str, row_hash: str) -> bool:
    return bool(
        db.scalar(
            select(LegacyImportRecord.id).where(
                LegacyImportRecord.source == source,
                LegacyImportRecord.row_hash == row_hash,
            )
        )
    )


def iter_payloads(rows: list[list[Any]]) -> Iterable[tuple[int, dict[str, Any]]]:
    if not rows:
        return
    headers = rows[0]
    for row_number, row in enumerate(rows[1:], start=2):
        payload = row_payload(headers, row)
        if any(clean(value) for value in payload.values()):
            yield row_number, payload


def import_clients(
    db: Session, batch: ImportBatch, rows: list[list[Any]], summary: dict[str, int]
) -> None:
    seen_hashes: set[str] = set()
    for row_number, payload in iter_payloads(rows):
        row_hash = payload_hash(SOURCE_CLIENTS, payload)
        if row_hash in seen_hashes or already_imported(db, SOURCE_CLIENTS, row_hash):
            summary["clients_duplicate"] += 1
            continue
        seen_hashes.add(row_hash)

        email = normalize_email(payload.get("Email"))
        platform_user_id = clean(payload.get("Telegram ID"))
        username = normalize_username(payload.get("Username"))
        display_name = clean(payload.get("Имя"))
        platform_raw = clean(payload.get("Телега_или_Макс")).lower()
        platform = "max" if "макс" in platform_raw or "max" in platform_raw else "telegram"
        first_seen_at = parse_datetime(
            first(payload, "Первая активность", "Дата создания")
        )

        if not email and not platform_user_id and not username:
            add_import_record(
                db,
                batch,
                SOURCE_CLIENTS,
                row_number,
                row_hash,
                payload,
                "needs_review",
                reason="no stable contact identifier",
            )
            summary["clients_needs_review"] += 1
            continue

        email_user = find_user_by_email(db, email)
        messenger_user = find_user_by_messenger(db, platform, platform_user_id)
        if email_user and messenger_user and email_user.id != messenger_user.id:
            add_import_record(
                db,
                batch,
                SOURCE_CLIENTS,
                row_number,
                row_hash,
                payload,
                "needs_review",
                reason="email and messenger resolve to different users",
            )
            summary["clients_needs_review"] += 1
            continue

        user = email_user or messenger_user or make_user(db, display_name, first_seen_at)
        if display_name and not user.display_name:
            user.display_name = display_name
        if first_seen_at and (user.first_seen_at is None or first_seen_at < user.first_seen_at):
            user.first_seen_at = first_seen_at
        attach_email(db, user, clean(payload.get("Email")), SOURCE_CLIENTS, first_seen_at)
        attach_or_update_messenger(
            db,
            user,
            platform,
            platform_user_id,
            username,
            display_name,
            first_seen_at,
        )

        source_raw = clean(payload.get("Источник:"))
        if source_raw:
            db.add(
                AttributionEvent(
                    user_id=user.id,
                    import_batch_id=batch.id,
                    event_type="legacy_first_seen",
                    source_raw=source_raw,
                    occurred_at=first_seen_at,
                )
            )
        add_import_record(
            db,
            batch,
            SOURCE_CLIENTS,
            row_number,
            row_hash,
            payload,
            "imported",
            user=user,
        )
        summary["clients_imported"] += 1
        db.flush()


def extract_attribution(url: str) -> dict[str, str | None]:
    if not url:
        return {}
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return {
        "utm_source": query.get("utm_source", [None])[0],
        "utm_medium": query.get("utm_medium", [None])[0],
        "utm_campaign": query.get("utm_campaign", [None])[0],
        "utm_content": query.get("utm_content", [None])[0],
        "utm_term": query.get("utm_term", [None])[0],
        "ref_code": query.get("ref", query.get("invite", [None]))[0],
    }


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


def import_payments(
    db: Session, batch: ImportBatch, rows: list[list[Any]], summary: dict[str, int]
) -> None:
    seen_hashes: set[str] = set()
    for row_number, payload in iter_payloads(rows):
        row_hash = payload_hash(SOURCE_PAYMENTS, payload)
        if row_hash in seen_hashes or already_imported(db, SOURCE_PAYMENTS, row_hash):
            summary["payments_duplicate"] += 1
            continue
        seen_hashes.add(row_hash)

        external_order_id = clean(payload.get("orderid")) or None
        external_payment_id = clean(payload.get("paymentid")) or None
        existing = db.scalar(
            select(Payment).where(
                Payment.source == SOURCE_PAYMENTS,
                or_(
                    and_(
                        Payment.external_order_id == external_order_id,
                        external_order_id is not None,
                    ),
                    and_(
                        Payment.external_payment_id == external_payment_id,
                        external_payment_id is not None,
                    ),
                ),
            )
        )
        if existing:
            summary["payments_duplicate"] += 1
            continue

        email_original = clean(payload.get("Email"))
        email = normalize_email(email_original)
        source_event_at = parse_datetime(payload.get("sent"))
        user = find_user_by_email(db, email)
        if user is None:
            user = make_user(db, clean(payload.get("Name")), source_event_at)
            attach_email(db, user, email_original, SOURCE_PAYMENTS, source_event_at)

        raw_product = clean(payload.get("products"))
        product = db.scalar(
            select(Product)
            .join(ProductAlias, ProductAlias.product_id == Product.id)
            .where(
                ProductAlias.source == SOURCE_PAYMENTS,
                ProductAlias.raw_name_exact == raw_product,
            )
        )
        payment_status = normalize_payment_status(payload)
        paid_at = source_event_at if payment_status == "paid" else None
        referer = clean(payload.get("referer"))
        payment = Payment(
            user_id=user.id,
            product_id=product.id if product else None,
            import_batch_id=batch.id,
            source=SOURCE_PAYMENTS,
            external_order_id=external_order_id,
            external_payment_id=external_payment_id,
            external_request_id=clean(payload.get("requestid")) or None,
            email_at_purchase=email_original or None,
            product_name_raw=raw_product,
            amount=parse_amount(payload.get("price")),
            currency=clean(first(payload, "Currency", "Валюта")) or "RUB",
            payment_status=payment_status,
            payment_system=clean(payload.get("paymentsystem")) or None,
            source_event_at=source_event_at,
            paid_at=paid_at,
            paid_at_is_estimated=paid_at is not None,
            external_form_id=clean(payload.get("formid")) or None,
            form_name_raw=clean(first(payload, "Form name", "Название формы")) or None,
            referer_raw=referer or None,
            landing_url=referer or None,
            raw_payload=payload,
        )
        db.add(payment)
        db.flush()

        if referer:
            db.add(
                AttributionEvent(
                    user_id=user.id,
                    import_batch_id=batch.id,
                    event_type="legacy_purchase_visit",
                    landing_url=referer,
                    occurred_at=source_event_at,
                    **extract_attribution(referer),
                )
            )

        if payment_status == "paid" and product and paid_at:
            for rule in active_access_rules(db, product.id, paid_at):
                db.add(
                    UserAccess(
                        user_id=user.id,
                        resource_id=rule.resource_id,
                        source_payment_id=payment.id,
                        source="paid_product_rule",
                        granted_at=paid_at,
                    )
                )
            summary["payments_access_granted"] += 1
        elif payment_status == "paid" and product is None:
            summary["payments_unmapped_product"] += 1

        add_import_record(
            db,
            batch,
            SOURCE_PAYMENTS,
            row_number,
            row_hash,
            payload,
            "imported" if product else "needs_review",
            user=user,
            payment=payment,
            reason=None if product else "unmapped product alias",
        )
        summary["payments_imported"] += 1
        db.flush()


def import_payload(db: Session, data: dict[str, Any]) -> dict[str, int]:
    cutoff = parse_datetime(data.get("standard_calories_cutoff"))
    if cutoff is None:
        raise ValueError("standard_calories_cutoff is required")

    batch = ImportBatch(source="google_legacy_crm")
    db.add(batch)
    db.flush()
    summary = {
        "clients_imported": 0,
        "clients_duplicate": 0,
        "clients_needs_review": 0,
        "payments_imported": 0,
        "payments_duplicate": 0,
        "payments_unmapped_product": 0,
        "payments_access_granted": 0,
    }
    seed_catalog(db, data.get("product_aliases", {}), cutoff)
    import_clients(db, batch, data.get("clients", []), summary)
    import_payments(db, batch, data.get("payments", []), summary)
    batch.status = "completed"
    batch.finished_at = datetime.now(tz=MOSCOW)
    batch.summary = summary
    db.commit()
    return summary


def main() -> None:
    data = json.load(sys.stdin)
    with SessionLocal() as db:
        try:
            summary = import_payload(db, data)
        except Exception:
            db.rollback()
            raise
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
