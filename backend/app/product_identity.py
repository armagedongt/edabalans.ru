from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Payment, Product
from app.product_catalog_service import tariff_public


CONFIRMED_PAYMENT_STATUSES = ("paid", "confirmed")

def tariff_name(db: Session, product_code: str | None) -> str | None:
    tariff = tariff_public(db, product_code or "")
    return tariff["name"] if tariff else None


def purchased_products(db: Session, user_id: uuid.UUID) -> list[dict]:
    """Return normalized purchases; payments remain the immutable sales ledger."""
    rows: Iterable[tuple[Payment, str | None, str | None]] = db.execute(
        select(Payment, Product.code, Product.name)
        .outerjoin(Product, Product.id == Payment.product_id)
        .where(
            Payment.user_id == user_id,
            Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES),
        )
        .order_by(
            Payment.paid_at.desc().nullslast(),
            Payment.source_event_at.desc().nullslast(),
            Payment.created_at.desc(),
        )
    ).all()
    seen: set[str] = set()
    result: list[dict] = []
    for payment, code, name in rows:
        identity = code or f"raw:{payment.product_name_raw.strip().casefold()}"
        if identity in seen:
            continue
        seen.add(identity)
        purchased_at = payment.paid_at or payment.source_event_at or payment.created_at
        if purchased_at and purchased_at.tzinfo is None:
            purchased_at = purchased_at.replace(tzinfo=timezone.utc)
        result.append(
            {
                "product_code": code,
                "product_name": name or payment.product_name_raw,
                "tariff": tariff_name(db, code) or "Основной",
                "purchased_at": purchased_at.isoformat() if purchased_at else None,
            }
        )
    return result
