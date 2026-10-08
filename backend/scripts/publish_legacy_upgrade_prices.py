"""Publish the approved transition prices by copying the active catalog."""
from decimal import Decimal
from app.database import SessionLocal
from app.models import PriceEntry
from app.pricing_service import (active_pricing_version, create_draft, draft_pricing_version,
                                pricing_revision, pricing_entry_map, publish_draft)
from app.legacy_upgrade_service import PACKAGE, PRICE_CODES


def publish(db):
    active = active_pricing_version(db)
    if active is None:
        raise RuntimeError("Active pricing catalog required")
    current = pricing_entry_map(db, active)
    approved = {PRICE_CODES["first"]: 1990, PRICE_CODES["day"]: 2500, PRICE_CODES["standard"]: 2990}
    if all(code in current and current[code].sale_amount == amount and current[code].enabled
           for code, amount in approved.items()):
        return {"status": "already_published", "version": active.version_number}
    if draft_pricing_version(db) is not None:
        raise RuntimeError("Existing pricing draft must be reconciled before publication")
    draft = create_draft(db, "owner-approved-legacy-transition", expected_active=pricing_revision(db, active))
    rows = pricing_entry_map(db, draft)
    for index, (code, amount) in enumerate(approved.items()):
        row = rows.get(code)
        if row is None:
            row = PriceEntry(version_id=draft.id, code=code, section="offer_stages",
                             name="Переход на все самостоятельные программы",
                             stage_code="legacy_upgrade", resource_codes=list(PACKAGE),
                             currency="RUB", sort_order=900 + index)
            db.add(row)
        row.sale_amount = Decimal(amount)
        row.regular_amount = Decimal(2990)
        row.compare_at_amount = Decimal(2990)
        row.enabled = True
    db.flush()
    publish_draft(db, draft, "owner-approved-legacy-transition")
    return {"status": "published", "version": draft.version_number}


if __name__ == "__main__":
    import json
    with SessionLocal() as db:
        print(json.dumps(publish(db)))
