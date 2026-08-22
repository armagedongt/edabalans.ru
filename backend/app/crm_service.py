from __future__ import annotations

import re
import uuid
from decimal import Decimal

from sqlalchemy import distinct, func, or_, select, text
from sqlalchemy.orm import Session

from app.models import (
    AttributionEvent,
    ClientNote,
    MessengerAccount,
    Payment,
    Product,
    Resource,
    Tag,
    User,
    UserAccess,
    UserEmail,
    UserPhone,
    UserTag,
)


def money(value: Decimal | None) -> float:
    return float(value or 0)


def summary(db: Session) -> dict:
    users = db.scalar(
        select(func.count(User.id)).where(User.merged_into_user_id.is_(None))
    ) or 0
    buyers = db.scalar(
        select(func.count(distinct(Payment.user_id))).where(
            Payment.payment_status == "paid", Payment.user_id.is_not(None)
        )
    ) or 0
    paid_payments = db.scalar(
        select(func.count(Payment.id)).where(Payment.payment_status == "paid")
    ) or 0
    revenue = db.scalar(
        select(func.sum(Payment.amount)).where(
            Payment.payment_status == "paid", Payment.currency == "RUB"
        )
    )
    return {
        "users": users,
        "buyers": buyers,
        "paid_payments": paid_payments,
        "revenue_rub": money(revenue),
    }


def _user_scalar_subqueries():
    email = (
        select(UserEmail.email_original)
        .where(UserEmail.user_id == User.id)
        .order_by(UserEmail.is_primary.desc(), UserEmail.created_at.asc())
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )
    telegram = (
        select(MessengerAccount.username)
        .where(
            MessengerAccount.user_id == User.id,
            MessengerAccount.platform == "telegram",
        )
        .order_by(MessengerAccount.created_at.asc())
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )
    purchases = (
        select(func.count(Payment.id))
        .where(Payment.user_id == User.id, Payment.payment_status == "paid")
        .correlate(User)
        .scalar_subquery()
    )
    ltv = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(
            Payment.user_id == User.id,
            Payment.payment_status == "paid",
            Payment.currency == "RUB",
        )
        .correlate(User)
        .scalar_subquery()
    )
    last_purchase = (
        select(func.max(Payment.paid_at))
        .where(Payment.user_id == User.id, Payment.payment_status == "paid")
        .correlate(User)
        .scalar_subquery()
    )
    return email, telegram, purchases, ltv, last_purchase


def list_users(
    db: Session,
    query: str = "",
    buyers_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    email, telegram, purchases, ltv, last_purchase = _user_scalar_subqueries()
    stmt = (
        select(
            User.id,
            User.display_name,
            User.status,
            User.data_origin,
            User.first_seen_at,
            email.label("email"),
            telegram.label("telegram"),
            purchases.label("purchase_count"),
            ltv.label("ltv_rub"),
            last_purchase.label("last_purchase_at"),
        )
        .where(User.merged_into_user_id.is_(None))
        .order_by(last_purchase.desc().nullslast(), User.created_at.desc())
        .limit(min(max(limit, 1), 250))
        .offset(max(offset, 0))
    )
    if buyers_only:
        stmt = stmt.where(purchases > 0)
    if query.strip():
        pattern = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                User.display_name.ilike(pattern),
                email.ilike(pattern),
                telegram.ilike(pattern),
            )
        )
    rows = db.execute(stmt).mappings().all()
    user_ids = [row["id"] for row in rows]
    access_by_user: dict[uuid.UUID, list[str]] = {user_id: [] for user_id in user_ids}
    if user_ids:
        access_rows = db.execute(
            select(UserAccess.user_id, Resource.code)
            .join(Resource, Resource.id == UserAccess.resource_id)
            .where(
                UserAccess.user_id.in_(user_ids),
                UserAccess.revoked_at.is_(None),
                or_(UserAccess.expires_at.is_(None), UserAccess.expires_at > func.now()),
            )
            .distinct()
            .order_by(Resource.code)
        ).all()
        for user_id, code in access_rows:
            access_by_user[user_id].append(code)
    return [
        {
            "id": str(row["id"]),
            "display_name": row["display_name"],
            "status": row["status"],
            "data_origin": row["data_origin"],
            "email": row["email"],
            "telegram": row["telegram"],
            "purchase_count": row["purchase_count"] or 0,
            "ltv_rub": money(row["ltv_rub"]),
            "last_purchase_at": row["last_purchase_at"],
            "first_seen_at": row["first_seen_at"],
            "accesses": access_by_user[row["id"]],
        }
        for row in rows
    ]


def list_payments(db: Session, limit: int = 200) -> list[dict]:
    rows = db.execute(
        select(Payment, User.display_name, Product.code, Product.name)
        .outerjoin(User, User.id == Payment.user_id)
        .outerjoin(Product, Product.id == Payment.product_id)
        .order_by(Payment.source_event_at.desc().nullslast(), Payment.created_at.desc())
        .limit(min(max(limit, 1), 500))
    ).all()
    return [
        {
            "id": str(payment.id),
            "user_id": str(payment.user_id) if payment.user_id else None,
            "display_name": display_name,
            "email": payment.email_at_purchase,
            "product_code": product_code,
            "product_name": product_name,
            "product_name_raw": payment.product_name_raw,
            "amount": money(payment.amount),
            "currency": payment.currency,
            "status": payment.payment_status,
            "paid_at": payment.paid_at,
            "source_event_at": payment.source_event_at,
        }
        for payment, display_name, product_code, product_name in rows
    ]


def user_detail(db: Session, user_id: uuid.UUID) -> dict | None:
    user = db.get(User, user_id)
    if user is None or user.merged_into_user_id is not None:
        return None
    emails = list(
        db.scalars(
            select(UserEmail)
            .where(UserEmail.user_id == user_id)
            .order_by(UserEmail.is_primary.desc(), UserEmail.created_at.asc())
        )
    )
    messengers = list(
        db.scalars(
            select(MessengerAccount)
            .where(MessengerAccount.user_id == user_id)
            .order_by(MessengerAccount.created_at.asc())
        )
    )
    phones = list(
        db.scalars(
            select(UserPhone)
            .where(UserPhone.user_id == user_id)
            .order_by(UserPhone.is_primary.desc(), UserPhone.created_at.asc())
        )
    )
    payments = db.execute(
        select(Payment, Product.code, Product.name)
        .outerjoin(Product, Product.id == Payment.product_id)
        .where(Payment.user_id == user_id)
        .order_by(Payment.source_event_at.desc().nullslast(), Payment.created_at.desc())
    ).all()
    accesses = db.execute(
        select(UserAccess, Resource.code, Resource.name)
        .join(Resource, Resource.id == UserAccess.resource_id)
        .where(UserAccess.user_id == user_id)
        .order_by(UserAccess.granted_at.desc())
    ).all()
    attribution = list(
        db.scalars(
            select(AttributionEvent)
            .where(AttributionEvent.user_id == user_id)
            .order_by(
                AttributionEvent.occurred_at.asc().nullslast(),
                AttributionEvent.created_at.asc(),
            )
        )
    )
    tags = db.execute(
        text(
            """
            SELECT DISTINCT
                COALESCE(target.id, source.id) AS id,
                COALESCE(target.name, source.name) AS name,
                COALESCE(target.category, source.category) AS category
            FROM user_tags assignment
            JOIN tags source ON source.id = assignment.tag_id
            LEFT JOIN tags target ON target.id = source.merged_into_tag_id
            WHERE assignment.user_id = :user_id
              AND COALESCE(target.status, source.status) <> 'ignored'
            ORDER BY name
            """
        ),
        {"user_id": user_id},
    ).mappings().all()
    notes = list(
        db.scalars(
            select(ClientNote)
            .where(ClientNote.user_id == user_id)
            .order_by(ClientNote.created_at.desc())
        )
    )
    paid = [payment for payment, _, _ in payments if payment.payment_status == "paid"]
    return {
        "id": str(user.id),
        "display_name": user.display_name,
        "status": user.status,
        "data_origin": user.data_origin,
        "first_seen_at": user.first_seen_at,
        "emails": [
            {
                "email": item.email_original,
                "primary": item.is_primary,
                "verification_status": item.verification_status,
            }
            for item in emails
        ],
        "messengers": [
            {
                "platform": item.platform,
                "platform_user_id": item.platform_user_id,
                "username": item.username,
                "first_name": item.first_name,
            }
            for item in messengers
        ],
        "phones": [
            {"phone": item.phone_original, "primary": item.is_primary, "source": item.source}
            for item in phones
        ],
        "purchase_count": len(paid),
        "ltv_rub": money(
            sum((payment.amount for payment in paid if payment.currency == "RUB"), Decimal())
        ),
        "payments": [
            {
                "id": str(payment.id),
                "product_code": product_code,
                "product_name": product_name,
                "product_name_raw": payment.product_name_raw,
                "amount": money(payment.amount),
                "currency": payment.currency,
                "status": payment.payment_status,
                "paid_at": payment.paid_at,
                "source_event_at": payment.source_event_at,
            }
            for payment, product_code, product_name in payments
        ],
        "accesses": [
            {
                "code": code,
                "name": name,
                "granted_at": access.granted_at,
                "expires_at": access.expires_at,
                "revoked_at": access.revoked_at,
            }
            for access, code, name in accesses
        ],
        "attribution": [
            {
                "event_type": item.event_type,
                "source": item.source_raw,
                "utm_source": item.utm_source,
                "utm_campaign": item.utm_campaign,
                "landing_url": item.landing_url,
                "occurred_at": item.occurred_at,
            }
            for item in attribution
        ],
        "tags": [
            {"id": str(item["id"]), "name": item["name"], "category": item["category"]}
            for item in tags
        ],
        "notes": [
            {"id": str(note.id), "body": note.body, "author": note.author, "created_at": note.created_at}
            for note in notes
        ],
    }


def update_user(db: Session, user_id: uuid.UUID, display_name: str | None) -> bool:
    user = db.get(User, user_id)
    if user is None or user.merged_into_user_id is not None:
        return False
    if display_name is not None:
        user.display_name = display_name.strip() or None
    db.commit()
    return True


def add_note(db: Session, user_id: uuid.UUID, body: str, author: str) -> ClientNote | None:
    user = db.get(User, user_id)
    if user is None or user.merged_into_user_id is not None:
        return None
    note = ClientNote(user_id=user_id, body=body.strip(), author=author)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def tag_code(name: str) -> str:
    code = re.sub(r"[^a-z0-9а-яё]+", "_", name.strip().lower(), flags=re.IGNORECASE)
    return code.strip("_")[:80]


def add_tag(db: Session, user_id: uuid.UUID, name: str) -> bool:
    user = db.get(User, user_id)
    if user is None or user.merged_into_user_id is not None:
        return False
    code = tag_code(name)
    if not code:
        return False
    tag = db.scalar(select(Tag).where(Tag.code == code))
    if tag is None:
        tag = Tag(code=code, name=name.strip(), category="manual", status="active")
        db.add(tag)
        db.flush()
    elif tag.merged_into_tag_id:
        tag = db.get(Tag, tag.merged_into_tag_id) or tag
    exists = db.scalar(
        select(UserTag.id).where(UserTag.user_id == user_id, UserTag.tag_id == tag.id)
    )
    if not exists:
        db.add(UserTag(user_id=user_id, tag_id=tag.id, source="manual_admin"))
    db.commit()
    return True


TAG_CATEGORIES = {
    "manual",
    "subscription",
    "content_action",
    "mailing_funnel",
    "source",
    "purchase_signal",
    "lottery",
    "other",
    "technical",
}
TAG_STATUSES = {"active", "ignored", "merged"}


def list_tags(
    db: Session, query: str = "", category: str = "", status: str = ""
) -> list[dict]:
    clauses = ["1 = 1"]
    params: dict[str, object] = {}
    if query.strip():
        clauses.append("t.name ILIKE :query")
        params["query"] = f"%{query.strip()}%"
    if category:
        clauses.append("t.category = :category")
        params["category"] = category
    if status:
        clauses.append("t.status = :status")
        params["status"] = status
    rows = db.execute(
        text(
            f"""
            SELECT
                t.id,
                t.name,
                t.category,
                t.status,
                t.merged_into_tag_id,
                target.name AS merged_into_name,
                count(DISTINCT ut.user_id) AS user_count,
                string_agg(DISTINCT ut.source, ', ' ORDER BY ut.source) AS sources
            FROM tags t
            LEFT JOIN tags target ON target.id = t.merged_into_tag_id
            LEFT JOIN user_tags ut ON ut.tag_id = t.id
            WHERE {' AND '.join(clauses)}
            GROUP BY t.id, target.name
            ORDER BY user_count DESC, lower(t.name)
            LIMIT 600
            """
        ),
        params,
    ).mappings().all()
    return [
        {
            "id": str(row["id"]),
            "name": row["name"],
            "category": row["category"],
            "status": row["status"],
            "merged_into_tag_id": str(row["merged_into_tag_id"]) if row["merged_into_tag_id"] else None,
            "merged_into_name": row["merged_into_name"],
            "user_count": row["user_count"] or 0,
            "sources": row["sources"] or "",
        }
        for row in rows
    ]


def update_tag(
    db: Session, tag_id: uuid.UUID, name: str, category: str, status: str
) -> bool:
    if category not in TAG_CATEGORIES or status not in {"active", "ignored"}:
        return False
    result = db.execute(
        text(
            """
            UPDATE tags
            SET name = :name, category = :category, status = :status,
                merged_into_tag_id = CASE WHEN :status = 'active' THEN NULL ELSE merged_into_tag_id END,
                updated_at = now()
            WHERE id = :tag_id
            """
        ),
        {"name": name.strip(), "category": category, "status": status, "tag_id": tag_id},
    )
    db.commit()
    return bool(result.rowcount)


def merge_tag(db: Session, source_tag_id: uuid.UUID, target_name: str) -> bool:
    source = db.get(Tag, source_tag_id)
    target = db.scalar(
        select(Tag).where(func.lower(Tag.name) == target_name.strip().lower(), Tag.status == "active")
    )
    if source is None or target is None or source.id == target.id:
        return False
    source.status = "merged"
    source.merged_into_tag_id = target.id
    source.updated_at = func.now()
    db.commit()
    return True
