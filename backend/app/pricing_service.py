from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PriceEntry, PricingVersion


def site_tariff_amount(
    entry: PriceEntry, *, personal_discount: Decimal = Decimal("0")
) -> Decimal:
    """Return the payable amount used by both the storefront and checkout."""
    return max(Decimal("0"), entry.sale_amount - personal_discount)


def amount_value(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value == value.to_integral() else float(value)


def version_entries(db: Session, version_id: uuid.UUID) -> list[PriceEntry]:
    return list(
        db.scalars(
            select(PriceEntry)
            .where(PriceEntry.version_id == version_id)
            .order_by(PriceEntry.section, PriceEntry.sort_order, PriceEntry.code)
        )
    )


def active_pricing_version(db: Session) -> PricingVersion | None:
    return db.scalar(
        select(PricingVersion).where(PricingVersion.status == "active")
    )


def draft_pricing_version(db: Session) -> PricingVersion | None:
    return db.scalar(
        select(PricingVersion).where(PricingVersion.status == "draft")
    )


def latest_pricing_version(db: Session) -> PricingVersion | None:
    return db.scalar(
        select(PricingVersion).order_by(PricingVersion.version_number.desc()).limit(1)
    )


def pricing_entry_map(db: Session, version: PricingVersion) -> dict[str, PriceEntry]:
    return {entry.code: entry for entry in version_entries(db, version.id)}


def serialize_entry(entry: PriceEntry) -> dict:
    return {
        "id": str(entry.id),
        "code": entry.code,
        "section": entry.section,
        "name": entry.name,
        "product_code": entry.product_code,
        "stage_code": entry.stage_code,
        "resource_codes": list(entry.resource_codes or []),
        "item_count": entry.item_count,
        "regular_amount": amount_value(entry.regular_amount),
        "compare_at_amount": amount_value(entry.compare_at_amount),
        "sale_amount": amount_value(entry.sale_amount),
        "currency": entry.currency,
        "enabled": entry.enabled,
        "sort_order": entry.sort_order,
        "metadata": dict(entry.metadata_json or {}),
    }


def serialize_version(db: Session, version: PricingVersion, *, include_entries: bool) -> dict:
    result = {
        "id": str(version.id),
        "version_number": version.version_number,
        "name": version.name,
        "status": version.status,
        "effective_from": version.effective_from.isoformat() if version.effective_from else None,
        "activated_at": version.activated_at.isoformat() if version.activated_at else None,
        "created_by": version.created_by,
        "activated_by": version.activated_by,
        "note": version.note,
        "created_at": version.created_at.isoformat(),
        "updated_at": version.updated_at.isoformat(),
    }
    if include_entries:
        result["entries"] = [serialize_entry(entry) for entry in version_entries(db, version.id)]
    return result


def create_draft(db: Session, admin: str) -> PricingVersion:
    current = draft_pricing_version(db)
    if current is not None:
        return current
    source = active_pricing_version(db) or latest_pricing_version(db)
    next_number = int(db.scalar(select(func.max(PricingVersion.version_number))) or 0) + 1
    draft = PricingVersion(
        version_number=next_number,
        name=f"Каталог цен v{next_number}",
        status="draft",
        created_by=admin,
        note="Черновик: не влияет на сайт и новые покупки до публикации и включения режима",
    )
    db.add(draft)
    db.flush()
    if source is not None:
        for entry in version_entries(db, source.id):
            db.add(
                PriceEntry(
                    version_id=draft.id,
                    code=entry.code,
                    section=entry.section,
                    name=entry.name,
                    product_code=entry.product_code,
                    stage_code=entry.stage_code,
                    resource_codes=list(entry.resource_codes or []),
                    item_count=entry.item_count,
                    regular_amount=entry.regular_amount,
                    compare_at_amount=entry.compare_at_amount,
                    sale_amount=entry.sale_amount,
                    currency=entry.currency,
                    enabled=entry.enabled,
                    sort_order=entry.sort_order,
                    metadata_json=dict(entry.metadata_json or {}),
                )
            )
    db.commit()
    db.refresh(draft)
    return draft


def publish_draft(db: Session, version: PricingVersion, admin: str) -> None:
    if version.status != "draft":
        raise ValueError("only a draft pricing version can be published")
    now = datetime.now(timezone.utc)
    current = active_pricing_version(db)
    if current is not None:
        current.status = "archived"
    version.status = "active"
    version.activated_at = now
    version.effective_from = now
    version.activated_by = admin
    db.commit()
