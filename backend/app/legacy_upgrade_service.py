from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.access_service import review_blocks_access
from app.course_access_service import active_resource_codes
from app.models import User, UserOffer
from app.pricing_service import active_pricing_version, pricing_entry_map, amount_value
from app.product_catalog_service import product_public

OFFER_CODE = "legacy-upgrade"
STAGE_CODE = "legacy_upgrade"
PACKAGE = ("ACCESS_MASTERCLASS", "ACCESS_CALORIES", "ACCESS_RECIPES")
PRICE_CODES = {"first": "legacy.upgrade.first", "day": "legacy.upgrade.day", "standard": "legacy.upgrade.standard"}


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def eligible(db: Session, user: User) -> bool:
    owned = active_resource_codes(db, user.id)
    return (user.status == "active" and user.merged_into_user_id is None
            and not review_blocks_access(user)
            and bool(owned.intersection({"ACCESS_MASTERCLASS_LEGACY", "ACCESS_CALORIES_LEGACY"}))
            and not set(PACKAGE).issubset(owned))


def offer_payload(db: Session, user: User, *, start: bool, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    empty = {"ok": True, "available": False, "offers": [], "expires_at": None, "focusable_product_codes": []}
    if not eligible(db, user):
        return empty
    empty["legacy_upgrade"] = True
    version = active_pricing_version(db)
    entries = pricing_entry_map(db, version) if version else {}
    if any(code not in entries or not entries[code].enabled for code in PRICE_CODES.values()):
        return empty
    if start:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
    window = db.scalar(select(UserOffer).where(UserOffer.user_id == user.id, UserOffer.stage_code == STAGE_CODE))
    if window is None:
        if not start:
            return empty
        window = UserOffer(user_id=user.id, stage_code=STAGE_CODE, started_at=now,
                           expires_at=now + timedelta(hours=24), status="active",
                           snapshot={"source": "account_visible_offer"})
        db.add(window)
        db.flush()
    started = aware(window.started_at)
    first_end, day_end = started + timedelta(minutes=10), started + timedelta(hours=24)
    stage = "first" if now < first_end else "day" if now < day_end else "standard"
    expires = first_end if stage == "first" else day_end if stage == "day" else None
    entry, regular = entries[PRICE_CODES[stage]], entries[PRICE_CODES["standard"]]
    owned = active_resource_codes(db, user.id)
    current = []
    for code, resource in (("masterclass", "ACCESS_MASTERCLASS"), ("calories", "ACCESS_CALORIES"), ("recipes", "ACCESS_RECIPES")):
        if resource in owned or resource + "_LEGACY" in owned:
            current.append({"name": product_public(db, code)["name"],
                            "edition": "updating" if resource in owned else "non_updating"})
    details = [{"code": code, "name": product_public(db, code)["name"]}
               for code in ("masterclass", "calories", "recipes")]
    card = {"code": OFFER_CODE, "title": "Все самостоятельные программы",
            "items": list(PACKAGE), "price": amount_value(entry.sale_amount),
            "regular_price": amount_value(regular.sale_amount),
            "price_entry_code": entry.code, "details": details}
    return {"ok": True, "available": True, "legacy_upgrade": True, "stage": stage,
            "server_now": now.isoformat(), "started_at": started.isoformat(),
            "expires_at": expires.isoformat() if expires else None,
            "pricing_version_id": str(version.id), "current": current,
            "offers": [card], "focusable_product_codes": []}
