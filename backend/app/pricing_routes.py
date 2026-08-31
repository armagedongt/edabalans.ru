from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
from threading import Lock
import time
from urllib.parse import urlsplit
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import Settings, get_settings
from app.database import get_db
from app.models import OfferCheckout, PricingVersion
from app.pricing_service import (
    active_pricing_version,
    create_draft,
    latest_pricing_version,
    pricing_entry_map,
    publish_draft,
    serialize_entry,
    serialize_version,
)
from app.product_catalog_service import tariff_public


router = APIRouter(tags=["pricing"])
PRICE_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,119}$")
PREVIEW_CHECKOUT_RATE_WINDOW_SECONDS = 60
PREVIEW_CHECKOUT_RATE_MAX = 10
_preview_checkout_rate_lock = Lock()
_preview_checkout_rate_state: dict[str, tuple[float, int]] = {}


class PriceEntryUpdate(BaseModel):
    code: str = Field(min_length=3, max_length=120)
    regular_amount: Decimal | None = Field(default=None, ge=0, le=10_000_000)
    compare_at_amount: Decimal | None = Field(default=None, ge=0, le=10_000_000)
    sale_amount: Decimal = Field(ge=0, le=10_000_000)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_prices(self):
        if self.compare_at_amount is not None and self.compare_at_amount < self.sale_amount:
            raise ValueError("compare_at_amount cannot be below sale_amount")
        if self.regular_amount is not None and self.regular_amount < self.sale_amount:
            raise ValueError("regular_amount cannot be below sale_amount")
        return self


class PricingDraftUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=10_000)
    entries: list[PriceEntryUpdate] = Field(min_length=1, max_length=200)


class PublicCheckoutIn(BaseModel):
    price_code: str = Field(min_length=3, max_length=120)


def enforce_preview_checkout_rate_limit(request: Request) -> None:
    client_key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _preview_checkout_rate_lock:
        started_at, requests = _preview_checkout_rate_state.get(
            client_key, (now, 0)
        )
        if now - started_at >= PREVIEW_CHECKOUT_RATE_WINDOW_SECONDS:
            started_at, requests = now, 0
        if requests >= PREVIEW_CHECKOUT_RATE_MAX:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "preview checkout rate limit exceeded",
            )
        _preview_checkout_rate_state[client_key] = (started_at, requests + 1)
        if len(_preview_checkout_rate_state) > 5_000:
            expired = [
                key
                for key, (window_start, _) in _preview_checkout_rate_state.items()
                if now - window_start >= PREVIEW_CHECKOUT_RATE_WINDOW_SECONDS
            ]
            for key in expired:
                _preview_checkout_rate_state.pop(key, None)


def enforce_preview_checkout_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "preview checkout origin required")
    origin_host = (urlsplit(origin).hostname or "").lower()
    request_host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    if origin_host != request_host:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "preview checkout origin rejected")


def safe_order_name(value: str) -> str:
    return re.sub(r"[\r\n=:]+", " ", value).strip()


@router.get("/admin/api/pricing")
def admin_pricing(
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    versions = list(
        db.scalars(select(PricingVersion).order_by(PricingVersion.version_number.desc()))
    )
    return {
        "ok": True,
        "live_consumption_enabled": settings.pricing_catalog_enabled,
        "versions": [serialize_version(db, version, include_entries=True) for version in versions],
    }


@router.post("/admin/api/pricing/drafts")
def admin_create_pricing_draft(
    admin: str = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    version = create_draft(db, admin)
    return {"ok": True, "version": serialize_version(db, version, include_entries=True)}


@router.put("/admin/api/pricing/versions/{version_id}")
def admin_update_pricing_draft(
    version_id: uuid.UUID,
    body: PricingDraftUpdate,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    version = db.get(PricingVersion, version_id)
    if version is None:
        raise HTTPException(404, "Версия цен не найдена")
    if version.status != "draft":
        raise HTTPException(409, "Опубликованную версию нельзя редактировать; создайте новый черновик")
    rows = pricing_entry_map(db, version)
    supplied = [item.code for item in body.entries]
    if len(supplied) != len(set(supplied)):
        raise HTTPException(422, "Код цены повторяется")
    if set(supplied) != set(rows):
        raise HTTPException(422, "Нельзя добавлять или удалять строки этим экраном")
    for item in body.entries:
        if not PRICE_CODE.match(item.code):
            raise HTTPException(422, f"Некорректный код цены: {item.code}")
        row = rows[item.code]
        row.regular_amount = item.regular_amount
        row.compare_at_amount = item.compare_at_amount
        row.sale_amount = item.sale_amount
        row.enabled = item.enabled
    version.name = body.name.strip()
    version.note = (body.note or "").strip() or None
    db.commit()
    db.refresh(version)
    return {"ok": True, "version": serialize_version(db, version, include_entries=True)}


@router.post("/admin/api/pricing/versions/{version_id}/publish")
def admin_publish_pricing_version(
    version_id: uuid.UUID,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    version = db.get(PricingVersion, version_id)
    if version is None:
        raise HTTPException(404, "Версия цен не найдена")
    try:
        publish_draft(db, version, admin)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "ok": True,
        "live_consumption_enabled": settings.pricing_catalog_enabled,
        "version": serialize_version(db, version, include_entries=True),
    }


def site_pricing_payload(db: Session, version: PricingVersion) -> dict:
    entries = []
    for entry in pricing_entry_map(db, version).values():
        if entry.section != "site_tariffs" or not entry.enabled:
            continue
        catalog_tariff = tariff_public(db, entry.product_code or "")
        entries.append(
            {
                **serialize_entry(entry),
                "name": catalog_tariff["name"] if catalog_tariff else entry.name,
                "descriptor": catalog_tariff["description"] if catalog_tariff else "",
                "products": catalog_tariff["products"] if catalog_tariff else [],
            }
        )
    entries.sort(key=lambda item: item["sort_order"])
    return {
        "ok": True,
        "version": version.version_number,
        "effective_from": version.effective_from.isoformat() if version.effective_from else None,
        "tariffs": entries,
    }


@router.get("/api/pricing/site")
def public_site_pricing(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict:
    if not settings.pricing_catalog_enabled:
        raise HTTPException(503, "Новый серверный каталог цен ещё не включён")
    version = active_pricing_version(db)
    if version is None:
        raise HTTPException(503, "Активная версия цен не опубликована")
    return site_pricing_payload(db, version)


@router.get("/api/pricing/site/preview")
def public_site_pricing_preview(db: Session = Depends(get_db)) -> dict:
    """Expose current display prices to noindex previews without enabling checkout."""
    version = active_pricing_version(db) or latest_pricing_version(db)
    if version is None:
        raise HTTPException(503, "Версия цен для preview не создана")
    return site_pricing_payload(db, version)


@router.post("/api/pricing/site/checkout")
def public_site_checkout(
    body: PublicCheckoutIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not settings.pricing_catalog_enabled:
        raise HTTPException(503, "Новый серверный каталог цен ещё не включён")
    version = active_pricing_version(db)
    if version is None:
        raise HTTPException(503, "Активная версия цен не опубликована")
    return create_site_checkout(db, version, body.price_code)


@router.post("/api/pricing/site/preview-checkout", include_in_schema=False)
def public_site_preview_checkout(
    body: PublicCheckoutIn, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Allow real cart testing only from the explicitly noindex homepage preview."""
    enforce_preview_checkout_origin(request)
    enforce_preview_checkout_rate_limit(request)
    version = active_pricing_version(db)
    if version is None:
        raise HTTPException(503, "Активная версия цен не опубликована")
    return create_site_checkout(db, version, body.price_code)


def create_site_checkout(
    db: Session, version: PricingVersion, price_code: str
) -> dict:
    entry = pricing_entry_map(db, version).get(price_code)
    if entry is None or entry.section != "site_tariffs" or not entry.enabled:
        raise HTTPException(404, "Тариф недоступен")
    now = datetime.now(timezone.utc)
    db.execute(
        delete(OfferCheckout).where(
            OfferCheckout.checkout_kind == "public_site",
            OfferCheckout.status == "pending",
            OfferCheckout.expires_at <= now,
        )
    )
    checkout = OfferCheckout(
        user_id=None,
        checkout_kind="public_site",
        pricing_version_id=version.id,
        price_entry_code=entry.code,
        offer_code=entry.code,
        title=entry.name,
        items=list(entry.resource_codes or []),
        amount=entry.sale_amount,
        expires_at=now + timedelta(hours=2),
    )
    db.add(checkout)
    db.flush()
    amount_text = format(entry.sale_amount, "f").rstrip("0").rstrip(".")
    command = f"#order:{safe_order_name(f'EB-{checkout.id.hex} {entry.name}')}={amount_text}"
    db.commit()
    return {
        "ok": True,
        "price_code": entry.code,
        "pricing_version": version.version_number,
        "cart_command": command,
        "expires_at": checkout.expires_at.isoformat(),
    }
