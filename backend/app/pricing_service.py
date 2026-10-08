from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from copy import deepcopy
import hashlib
import json
import re
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PriceEntry, PricingVersion

AUTHORING_METADATA = "_editorial_pricing"


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
            .execution_options(populate_existing=True)
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
        source = pricing_source(db, version)
        result.update(source=source, revision=pricing_revision(db, version),
                      semantic_sha256=source_hash(source, semantic=True),
                      base_active=base_active(db, version),
                      authoring_ready=version.status == "draft" and draft_base_known(db, version))
    return result


def pricing_source(db: Session, version: PricingVersion) -> dict:
    entries = []
    for entry in version_entries(db, version.id):
        item = serialize_entry(entry)
        item.pop("id")
        for field in ("regular_amount", "compare_at_amount", "sale_amount"):
            value = getattr(entry, field)
            item[field] = None if value is None else format(value, ".2f")
        entries.append(item)
    return {"schema_version": 1, "name": version.name, "note": version.note, "entries": entries}


def source_hash(source: dict, *, semantic: bool = False) -> str:
    source = deepcopy(source)
    source["entries"].sort(key=lambda item: item["code"])
    if semantic:
        if source["entries"]:
            first = source["entries"][0]
            if valid_authoring_metadata(first["metadata"].get(AUTHORING_METADATA)):
                first["metadata"].pop(AUTHORING_METADATA)
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def valid_authoring_metadata(marker) -> bool:
    if not isinstance(marker, dict) or set(marker) != {"schema_version", "owner", "base_active"} or type(marker["schema_version"]) is not int or marker["schema_version"] != 1 or marker["owner"] != "platform.commerce":
        return False
    base = marker["base_active"]
    if base is None:
        return True
    if not isinstance(base, dict) or set(base) != {"id", "version_number", "sha256"} or type(base["version_number"]) is not int or base["version_number"] < 1:
        return False
    try:
        uuid.UUID(base["id"])
    except (ValueError, TypeError, AttributeError):
        return False
    return isinstance(base["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", base["sha256"]) is not None


def pricing_revision(db: Session, version: PricingVersion) -> dict:
    return {"id": str(version.id), "version_number": version.version_number,
            "sha256": source_hash(pricing_source(db, version))}


def _marker(db: Session, version: PricingVersion) -> dict | None:
    entries = version_entries(db, version.id)
    if not entries:
        return None
    marker = (min(entries, key=lambda entry: entry.code).metadata_json or {}).get(AUTHORING_METADATA)
    if valid_authoring_metadata(marker):
        return marker
    return None


def _initial_draft(db: Session, version: PricingVersion) -> bool:
    # The migration's sole initial draft predates authoring metadata and has no
    # possible published base. Other legacy drafts are never silently adopted.
    return version.status == "draft" and version.version_number == 1 and db.scalar(select(func.count(PricingVersion.id))) == 1


def base_active(db: Session, version: PricingVersion) -> dict | None:
    marker = _marker(db, version)
    return marker["base_active"] if marker else None


def draft_base_known(db: Session, version: PricingVersion) -> bool:
    return _marker(db, version) is not None or _initial_draft(db, version)


def lock_active(db: Session, expected: dict | None) -> PricingVersion | None:
    if expected:
        # Lock the expected stable identity, then reread active after waiting.
        db.scalar(select(PricingVersion).where(PricingVersion.id == uuid.UUID(expected["id"]))
                  .with_for_update().execution_options(populate_existing=True))
    current = db.scalar(select(PricingVersion).where(PricingVersion.status == "active")
                        .execution_options(populate_existing=True))
    if (current is None) != (expected is None) or (current and pricing_revision(db, current) != expected):
        raise HTTPException(409, "Действующая версия цен изменилась; обновите каталог")
    return current


def lock_version(db: Session, version_id: uuid.UUID, expected: dict) -> PricingVersion:
    version = db.scalar(select(PricingVersion).where(PricingVersion.id == version_id)
                        .with_for_update().execution_options(populate_existing=True))
    if version is None:
        raise HTTPException(404, "Версия цен не найдена")
    if pricing_revision(db, version) != expected:
        raise HTTPException(409, "Черновик цен изменился; обновите каталог")
    return version


def check_draft_base(db: Session, version: PricingVersion, expected: dict | None) -> None:
    if not draft_base_known(db, version) or base_active(db, version) != expected:
        raise HTTPException(409, "Черновик создан на другой версии цен; объедините изменения")


def create_draft(db: Session, admin: str, *, expected_active: dict | None) -> PricingVersion:
    source = lock_active(db, expected_active)
    current = draft_pricing_version(db)
    if current is not None:
        raise HTTPException(409, "Уже существует черновик цен; получите его и объедините изменения")
    if source is None:
        raise HTTPException(409, "Первоначальный каталог требует отдельной настройки")
    next_number = int(db.scalar(select(func.max(PricingVersion.version_number))) or 0) + 1
    draft = PricingVersion(
        version_number=next_number,
        name=source.name,
        status="draft",
        created_by=admin,
        note=source.note,
    )
    db.add(draft)
    db.flush()
    if source is not None:
        entries = version_entries(db, source.id)
        if not entries:
            raise HTTPException(409, "В действующем каталоге отсутствуют строки цен")
        first_code = min(entry.code for entry in entries)
        for entry in entries:
            metadata = deepcopy(entry.metadata_json or {})
            existing = metadata.get(AUTHORING_METADATA)
            if existing is not None and not valid_authoring_metadata(existing):
                raise HTTPException(409, "Конфликт служебного поля каталога цен")
            if entry.code == first_code:
                metadata[AUTHORING_METADATA] = {"schema_version": 1, "owner": "platform.commerce", "base_active": expected_active}
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
                    metadata_json=metadata,
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
        # PostgreSQL permits only one active pricing version.  Flush the
        # archival before assigning the draft the active state so the unique
        # constraint is respected independently of ORM update ordering.
        db.flush()
    version.status = "active"
    version.activated_at = now
    version.effective_from = now
    version.activated_by = admin
    db.commit()
    db.refresh(version)
