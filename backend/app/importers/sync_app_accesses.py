from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Product, ProductAccessRule, Resource, UserAccess


PRODUCT_RESOURCES = {
    "MASTERCLASS_BASIC": "dqs",
    "MASTERCLASS_CONSULT": "dqs",
    "MASTERCLASS_RECIPES": "dqs",
    "TRAINING_COURSE": "strength",
    "CALORIES_COURSE": "metabolism",
}

LEGACY_RESOURCES = {
    "ACCESS_MASTERCLASS": "dqs",
    "ACCESS_STRENGTH": "strength",
    "ACCESS_CALORIES": "metabolism",
}


def run() -> dict[str, int]:
    summary = {"rules_created": 0, "accesses_created": 0}
    with SessionLocal() as db:
        products = {item.code: item for item in db.scalars(select(Product)).all()}
        resources = {item.code: item for item in db.scalars(select(Resource)).all()}

        for product_code, resource_code in PRODUCT_RESOURCES.items():
            product = products.get(product_code)
            resource = resources.get(resource_code)
            if not product or not resource:
                continue
            exists = db.scalar(
                select(ProductAccessRule).where(
                    ProductAccessRule.product_id == product.id,
                    ProductAccessRule.resource_id == resource.id,
                )
            )
            if not exists:
                db.add(ProductAccessRule(product_id=product.id, resource_id=resource.id))
                summary["rules_created"] += 1

        for legacy_code, resource_code in LEGACY_RESOURCES.items():
            legacy = resources.get(legacy_code)
            target = resources.get(resource_code)
            if not legacy or not target:
                continue
            legacy_accesses = db.scalars(
                select(UserAccess).where(
                    UserAccess.resource_id == legacy.id,
                    UserAccess.revoked_at.is_(None),
                )
            ).all()
            for old in legacy_accesses:
                exists = db.scalar(
                    select(UserAccess).where(
                        UserAccess.user_id == old.user_id,
                        UserAccess.resource_id == target.id,
                        UserAccess.revoked_at.is_(None),
                    ).limit(1)
                )
                if exists:
                    continue
                db.add(UserAccess(
                    user_id=old.user_id,
                    resource_id=target.id,
                    source_payment_id=old.source_payment_id,
                    source="resource_migration",
                    granted_at=old.granted_at or datetime.now(timezone.utc),
                    expires_at=old.expires_at,
                ))
                summary["accesses_created"] += 1
        db.commit()
    return summary


if __name__ == "__main__":
    print(run())
