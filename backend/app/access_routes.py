from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access_service import (
    active_link,
    amount_number,
    complete_review,
    create_link_token,
    grant_resources,
    link_by_token,
    resources_for_codes,
    review_blocks_access,
    user_for_email,
)
from app.auth import require_admin
from app.config import Settings, get_settings
from app.database import get_db
from app.legal_service import (
    accept_current_legal_documents,
    legal_status_payload,
)
from app.models import (
    AdminAppEdit,
    OfferCheckout,
    PersonalAccessLink,
    Resource,
    User,
    UserAccess,
    UserEmail,
)
from app.product_identity import purchased_products
from app.product_catalog_service import product_public


router = APIRouter(tags=["access-links"])


class LinkActionIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class LegalAcceptancesIn(LinkActionIn):
    document_codes: list[str] = Field(min_length=2, max_length=2)


class PersonalLinkCreateIn(BaseModel):
    resource_codes: list[str] = Field(min_length=1, max_length=20)
    final_amount: Decimal = Field(ge=0, le=10_000_000)
    standard_amount: Decimal | None = Field(default=None, ge=0, le=10_000_000)
    expires_days: int = Field(default=14, ge=1, le=365)
    fully_unlocked: bool = False


def aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def clean_order_name(value: str) -> str:
    return re.sub(r"[\r\n=:]+", " ", value).strip()


def matching_link(
    db: Session, token: str, email: str, *, for_update: bool = False
) -> tuple[PersonalAccessLink, User]:
    link = link_by_token(db, token, for_update=for_update)
    if link is None:
        raise HTTPException(404, "Персональная ссылка не найдена")
    user = user_for_email(db, email)
    if user is None or user.id != link.user_id:
        raise HTTPException(403, "Эта ссылка создана для другого аккаунта Tilda")
    if link.status in {"claimed", "paid"}:
        return link, user
    if not active_link(link):
        raise HTTPException(410, "Срок действия персональной ссылки закончился")
    return link, user


def link_payload(db: Session, link: PersonalAccessLink, user: User) -> dict:
    resources = resources_for_codes(db, list(link.resource_codes or []))
    email = db.scalar(
        select(UserEmail.email_normalized)
        .where(UserEmail.user_id == user.id)
        .order_by(UserEmail.is_primary.desc(), UserEmail.created_at.asc())
        .limit(1)
    ) or ""
    standard = amount_number(link.standard_amount)
    final = amount_number(link.final_amount)
    return {
        "ok": True,
        "mode": link.mode,
        "status": link.status,
        "email": email,
        "resources": [
            {
                "code": code,
                "name": resources[code].name,
                "unlock_mode": (link.unlock_modes or {}).get(code, "paced"),
            }
            for code in link.resource_codes
        ],
        "standard_amount": standard,
        "final_amount": final,
        "saving": amount_number(link.standard_amount - link.final_amount)
        if link.standard_amount is not None
        else None,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
    }


@router.get("/api/access/status")
def access_status(email: str, db: Session = Depends(get_db)) -> dict:
    user = user_for_email(db, email)
    if user is None:
        return {"ok": True, "state": "unknown", "message": "Аккаунт пока не связан с CRM"}
    return {
        "ok": True,
        "state": "review_required" if review_blocks_access(user) else "ready",
        "review_status": user.access_review_status,
        "message": (
            "Исторические покупки требуют решения Сергея. Напишите Сергею и укажите email личного кабинета."
            if review_blocks_access(user)
            else "Доступы проверены"
        ),
    }


def account_payload(email: str, db: Session) -> dict:
    user = user_for_email(db, email)
    if user is None:
        return {
            "ok": True,
            "state": "review_required",
            "review_status": "unknown",
            "message": "Аккаунт пока не связан с CRM. Напишите Сергею и укажите email личного кабинета.",
            "legal": None,
            "courses": [],
        }
    if review_blocks_access(user):
        return {
            "ok": True,
            "state": "review_required",
            "review_status": user.access_review_status,
            "message": "Нужно решение Сергея по вашим прежним покупкам. Напишите ему и укажите email личного кабинета.",
            "legal": legal_status_payload(db, user.id),
            "courses": [],
        }

    legal = legal_status_payload(db, user.id)
    now = datetime.now(timezone.utc)
    owned = set(
        db.scalars(
            select(Resource.code)
            .join(UserAccess, UserAccess.resource_id == Resource.id)
            .where(
                UserAccess.user_id == user.id,
                UserAccess.revoked_at.is_(None),
                UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now),
                Resource.status == "active",
            )
        )
    )
    definitions = []
    for account_code, catalog_code in (
        ("masterclass", "masterclass"), ("recipes", "recipes"),
        ("calories", "calories"), ("strength", "training"),
        ("recordings", "recordings"),
    ):
        definition = product_public(db, catalog_code)
        definition["account_code"] = account_code
        definitions.append(definition)
    purchases = purchased_products(db, user.id)
    masterclass_purchase = next(
        (item for item in purchases if str(item.get("product_code") or "").startswith("MASTERCLASS_")),
        None,
    )
    courses = []
    for definition in definitions:
        code = definition["account_code"]
        has_access = definition["resource"] in owned
        item = {
                "code": code,
                "title": definition["name"],
                "summary": definition["description"],
                "resource": definition["resource"],
                "owned": has_access,
                "state": "available" if has_access and definition["ready"] else "preparing" if has_access else "not_owned",
                "app": definition["app"] if has_access and definition["ready"] and not legal["required"] else None,
            }
        if code == "masterclass" and masterclass_purchase:
            item["tariff"] = masterclass_purchase["tariff"]
        courses.append(item)
    return {
        "ok": True,
        "state": "ready",
        "review_status": user.access_review_status,
        "email": email.strip().lower(),
        "legal": legal,
        "purchased_products": purchases,
        "courses": courses,
    }


@router.get("/api/account")
def account_catalog(email: str, db: Session = Depends(get_db)) -> dict:
    """Universal Members Area home; Tilda supplies identity, PostgreSQL supplies data."""
    return account_payload(email, db)


@router.post("/api/account/legal-acceptances")
def accept_account_legal_documents(
    body: LegalAcceptancesIn,
    db: Session = Depends(get_db),
) -> dict:
    user = user_for_email(db, body.email)
    if user is None:
        raise HTTPException(404, "Аккаунт пока не связан с CRM")
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    try:
        accept_current_legal_documents(
            db,
            user.id,
            body.document_codes,
            source="tilda_members_area",
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return account_payload(body.email, db)


@router.post("/api/access/registration-seen")
def registration_seen(
    body: LinkActionIn,
    db: Session = Depends(get_db),
) -> dict:
    user = user_for_email(db, body.email)
    if user is None:
        return {"ok": True, "state": "unknown"}
    if user.access_review_status == "waiting_registration":
        user.access_review_status = "pending"
        user.tilda_access_status = "pending"
        db.commit()
    return {"ok": True, "state": "review_required" if review_blocks_access(user) else "ready"}


@router.get("/api/access-links/{token}")
def personal_link(token: str, email: str, db: Session = Depends(get_db)) -> dict:
    link, user = matching_link(db, token, email)
    return link_payload(db, link, user)


@router.post("/api/access-links/{token}/claim")
def claim_personal_link(token: str, body: LinkActionIn, db: Session = Depends(get_db)) -> dict:
    link, user = matching_link(db, token, body.email, for_update=True)
    if link.mode != "free":
        raise HTTPException(409, "Это платное предложение")
    if link.status == "claimed":
        return link_payload(db, link, user)
    grant_resources(
        db,
        user,
        list(link.resource_codes or []),
        source="personal_free_link",
        unlock_modes=dict(link.unlock_modes or {}),
    )
    complete_review(user, "Права подтверждены персональной бесплатной ссылкой Сергея")
    link.status = "claimed"
    link.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return link_payload(db, link, user)


@router.post("/api/access-links/{token}/checkout")
def personal_link_checkout(token: str, body: LinkActionIn, db: Session = Depends(get_db)) -> dict:
    link, user = matching_link(db, token, body.email, for_update=True)
    if link.mode != "paid":
        raise HTTPException(409, "Это бесплатная ссылка")
    if link.status == "paid":
        return {"ok": True, "status": "paid"}
    checkout = db.get(OfferCheckout, link.checkout_id) if link.checkout_id else None
    now = datetime.now(timezone.utc)
    if checkout is None or checkout.status != "pending" or aware_utc(checkout.expires_at) <= now:
        link_expires = aware_utc(link.expires_at)
        checkout = OfferCheckout(
            user_id=user.id,
            offer_code=f"personal:{link.id}",
            title="Персональное предложение Сергея",
            items=list(link.resource_codes or []),
            amount=link.final_amount,
            expires_at=min(link_expires, now + timedelta(hours=2)) if link_expires else now + timedelta(hours=2),
        )
        db.add(checkout)
        db.flush()
        link.checkout_id = checkout.id
    command = f"#order:{clean_order_name(f'EB-{checkout.id.hex} Персональное предложение')}={amount_number(checkout.amount)}"
    db.commit()
    return {"ok": True, "cart_command": command, "expires_at": checkout.expires_at.isoformat()}


@router.post("/admin/api/users/{user_id}/personal-access-links")
def create_personal_link(
    user_id: uuid.UUID,
    body: PersonalLinkCreateIn,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = db.get(User, user_id)
    if user is None or user.merged_into_user_id is not None:
        raise HTTPException(404, "Пользователь не найден")
    resources = resources_for_codes(db, body.resource_codes)
    token, token_hash = create_link_token()
    mode = "free" if body.final_amount == 0 else "paid"
    unlock_modes = {
        code: "fully_unlocked" if body.fully_unlocked else "paced"
        for code in resources
    }
    url = f"{settings.personal_access_page_url}?access_token={token}"
    names = ", ".join(resources[code].name for code in body.resource_codes)
    if mode == "free":
        message_template = f"Для вас подготовлен бесплатный доступ: {names}. Откройте ссылку из своего личного кабинета: {{personal_link}}"
    else:
        price = amount_number(body.final_amount)
        discount = ""
        if body.standard_amount is not None and body.standard_amount > body.final_amount:
            discount = f" Обычная стоимость — {amount_number(body.standard_amount)} ₽."
        message_template = f"Для вас подготовлено персональное предложение: {names}.{discount} Итоговая стоимость — {price} ₽. Открыть и оплатить: {{personal_link}}"
    telegram_text = message_template.replace("{personal_link}", url)
    link = PersonalAccessLink(
        user_id=user.id,
        token_hash=token_hash,
        mode=mode,
        resource_codes=list(resources),
        unlock_modes=unlock_modes,
        standard_amount=body.standard_amount,
        final_amount=body.final_amount,
        expires_at=datetime.now(timezone.utc) + timedelta(days=body.expires_days),
        created_by=admin,
        telegram_text=message_template,
    )
    db.add(link)
    db.add(
        AdminAppEdit(
            admin_username=admin,
            target_user_id=user.id,
            app_code="crm",
            action="create_personal_access_link",
            details={
                "mode": mode,
                "resource_codes": list(resources),
                "final_amount": str(body.final_amount),
                "fully_unlocked": body.fully_unlocked,
            },
        )
    )
    db.commit()
    return {"ok": True, "url": url, "telegram_text": telegram_text, "mode": mode}


@router.get("/admin/api/users/{user_id}/personal-access-links")
def list_personal_links(
    user_id: uuid.UUID,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    rows = list(
        db.scalars(
            select(PersonalAccessLink)
            .where(PersonalAccessLink.user_id == user_id)
            .order_by(PersonalAccessLink.created_at.desc())
        )
    )
    return {
        "links": [
            {
                "id": str(item.id),
                "mode": item.mode,
                "status": item.status,
                "resources": item.resource_codes,
                "final_amount": amount_number(item.final_amount),
                "created_at": item.created_at.isoformat(),
                "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                "telegram_text": item.telegram_text,
            }
            for item in rows
        ]
    }
