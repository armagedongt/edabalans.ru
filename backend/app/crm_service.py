from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Uuid, bindparam, distinct, exists, func, or_, select, text
from sqlalchemy.orm import Session

from app.models import (
    AttributionEvent,
    ClientNote,
    LegacyImportRecord,
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
    AdminAppEdit,
    MasterclassEvent,
    QuestionnaireAnswer,
    QuestionnaireRun,
    UserOffer,
)
from app.masterclass_routes import (
    CLOSING_QUESTIONS,
    CURRENT_DIET_QUESTIONS,
    ONBOARDING_QUESTIONS,
)
from app.product_identity import purchased_products, tariff_name

CONFIRMED_PAYMENT_STATUSES = ("paid", "confirmed")
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def money(value: Decimal | None) -> float:
    return float(value or 0)


def summary(db: Session) -> dict:
    users = db.scalar(
        select(func.count(User.id)).where(User.merged_into_user_id.is_(None))
    ) or 0
    buyers = db.scalar(
        select(func.count(distinct(Payment.user_id))).where(
            Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES), Payment.user_id.is_not(None)
        )
    ) or 0
    paid_payments = db.scalar(
        select(func.count(Payment.id)).where(Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES))
    ) or 0
    revenue = db.scalar(
        select(func.sum(Payment.amount)).where(
            Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES),
            Payment.currency == "RUB",
            Payment.amount_is_estimated.is_(False),
        )
    )
    estimated_revenue = db.scalar(
        select(func.sum(Payment.amount)).where(
            Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES),
            Payment.currency == "RUB",
            Payment.amount_is_estimated.is_(True),
        )
    )
    tilda_members = db.scalar(
        select(func.count(distinct(LegacyImportRecord.user_id))).where(
            LegacyImportRecord.source.like("tilda_members_%"),
            LegacyImportRecord.status == "imported",
            LegacyImportRecord.user_id.is_not(None),
        )
    ) or 0
    access_reviews = db.scalar(
        select(func.count(User.id)).where(
            User.merged_into_user_id.is_(None),
            User.access_review_status != "not_required",
        )
    ) or 0
    return {
        "users": users,
        "buyers": buyers,
        "paid_payments": paid_payments,
        "revenue_rub": money(revenue),
        "estimated_revenue_rub": money(estimated_revenue),
        "tilda_members": tilda_members,
        "access_reviews": access_reviews,
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
        .where(Payment.user_id == User.id, Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES))
        .correlate(User)
        .scalar_subquery()
    )
    actual_ltv = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(
            Payment.user_id == User.id,
            Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES),
            Payment.currency == "RUB",
            Payment.amount_is_estimated.is_(False),
        )
        .correlate(User)
        .scalar_subquery()
    )
    estimated_ltv = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(
            Payment.user_id == User.id,
            Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES),
            Payment.currency == "RUB",
            Payment.amount_is_estimated.is_(True),
        )
        .correlate(User)
        .scalar_subquery()
    )
    last_purchase = (
        select(func.max(Payment.paid_at))
        .where(Payment.user_id == User.id, Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES))
        .correlate(User)
        .scalar_subquery()
    )
    return email, telegram, purchases, actual_ltv, estimated_ltv, last_purchase


def list_users(
    db: Session,
    query: str = "",
    buyers_only: bool = False,
    buyer_kind: str = "all", product_code: str = "", first_seen_from: date | None = None,
    first_seen_to: date | None = None, masterclass_access: bool | None = None, tag_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    email, telegram, purchases, actual_ltv, estimated_ltv, last_purchase = _user_scalar_subqueries()
    stmt = (
        select(
            User.id,
            User.display_name,
            User.status,
            User.data_origin,
            User.first_seen_at,
            User.access_review_status,
            User.tilda_access_status,
            email.label("email"),
            telegram.label("telegram"),
            purchases.label("purchase_count"),
            actual_ltv.label("ltv_rub"),
            estimated_ltv.label("estimated_ltv_rub"),
            last_purchase.label("last_purchase_at"),
        )
        .where(User.merged_into_user_id.is_(None))
        .order_by(last_purchase.desc().nullslast(), User.created_at.desc())
        .limit(min(max(limit, 1), 250))
        .offset(max(offset, 0))
    )
    if buyers_only or buyer_kind == "buyers":
        stmt = stmt.where(purchases > 0)
    elif buyer_kind == "non_buyers": stmt = stmt.where(purchases == 0)
    if product_code: stmt = stmt.where(exists(select(Payment.id).join(Product, Product.id == Payment.product_id).where(Payment.user_id == User.id, Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES), Product.code == product_code)))
    if first_seen_from: stmt = stmt.where(User.first_seen_at >= datetime.combine(first_seen_from, time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc))
    if first_seen_to: stmt = stmt.where(User.first_seen_at < datetime.combine(first_seen_to + timedelta(days=1), time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc))
    if masterclass_access is not None:
        access_exists = exists(select(UserAccess.id).join(Resource, Resource.id == UserAccess.resource_id).where(UserAccess.user_id == User.id, Resource.code == "ACCESS_MASTERCLASS", UserAccess.revoked_at.is_(None), or_(UserAccess.expires_at.is_(None), UserAccess.expires_at > func.now())))
        stmt = stmt.where(access_exists if masterclass_access else ~access_exists)
    if tag_id: stmt = stmt.where(exists(select(UserTag.user_id).where(UserTag.user_id == User.id, UserTag.tag_id == tag_id)))
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
            "estimated_ltv_rub": money(row["estimated_ltv_rub"]),
            "total_ltv_rub": money(row["ltv_rub"]) + money(row["estimated_ltv_rub"]),
            "last_purchase_at": row["last_purchase_at"],
            "first_seen_at": row["first_seen_at"],
            "access_review_status": row["access_review_status"],
            "tilda_access_status": row["tilda_access_status"],
            "accesses": access_by_user[row["id"]],
        }
        for row in rows
    ]


def list_payment_products(db: Session) -> list[dict]:
    rows = db.execute(
        select(Product.code, Product.name)
        .join(Payment, Payment.product_id == Product.id)
        .distinct()
        .order_by(Product.name)
    ).all()
    return [{"code": code, "name": name} for code, name in rows]


def list_payments(
    db: Session,
    limit: int = 200,
    query: str = "",
    product_code: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    amount_kind: str = "all",
) -> list[dict]:
    stmt = (
        select(Payment, User.display_name, Product.code, Product.name)
        .outerjoin(User, User.id == Payment.user_id)
        .outerjoin(Product, Product.id == Payment.product_id)
        .order_by(Payment.source_event_at.desc().nullslast(), Payment.created_at.desc())
        .limit(min(max(limit, 1), 500))
    )
    if query.strip():
        pattern = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                User.display_name.ilike(pattern),
                Payment.email_at_purchase.ilike(pattern),
                Payment.product_name_raw.ilike(pattern),
                Payment.raw_payload["payer_name"].as_string().ilike(pattern),
            )
        )
    if product_code.strip():
        stmt = stmt.where(Product.code == product_code.strip())
    event_date = func.coalesce(Payment.paid_at, Payment.source_event_at, Payment.created_at)
    if date_from:
        stmt = stmt.where(event_date >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(event_date <= datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    if amount_kind == "actual":
        stmt = stmt.where(Payment.amount_is_estimated.is_(False))
    elif amount_kind == "estimated":
        stmt = stmt.where(Payment.amount_is_estimated.is_(True))
    rows = db.execute(stmt).all()
    return [
        {
            "id": str(payment.id),
            "user_id": str(payment.user_id) if payment.user_id else None,
            "display_name": display_name,
            "payer_name": (payment.raw_payload or {}).get("payer_name"),
            "email": payment.email_at_purchase,
            "product_code": product_code,
            "product_name": product_name,
            "product_name_raw": payment.product_name_raw,
            "amount": money(payment.amount) if payment.amount is not None else None,
            "amount_is_estimated": payment.amount_is_estimated,
            "currency": payment.currency,
            "status": payment.payment_status,
            "review_status": payment.review_status,
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
              AND COALESCE(target.status, source.status) = 'active'
            ORDER BY name
            """
        ).bindparams(bindparam("user_id", type_=Uuid(as_uuid=True))),
        {"user_id": user_id},
    ).mappings().all()
    notes = list(
        db.scalars(
            select(ClientNote)
            .where(ClientNote.user_id == user_id)
            .order_by(ClientNote.created_at.desc())
        )
    )
    tilda_snapshot = db.scalar(
        select(LegacyImportRecord)
        .where(
            LegacyImportRecord.user_id == user_id,
            LegacyImportRecord.source.like("tilda_members_%"),
            LegacyImportRecord.status == "imported",
        )
        .order_by(LegacyImportRecord.created_at.desc())
        .limit(1)
    )
    questionnaire_runs = list(
        db.scalars(
            select(QuestionnaireRun)
            .where(QuestionnaireRun.user_id == user_id)
            .order_by(QuestionnaireRun.created_at.asc())
        )
    )
    answers_by_run: dict[uuid.UUID, list[QuestionnaireAnswer]] = {
        run.id: [] for run in questionnaire_runs
    }
    if questionnaire_runs:
        for answer in db.scalars(
            select(QuestionnaireAnswer)
            .where(QuestionnaireAnswer.run_id.in_(answers_by_run))
            .order_by(QuestionnaireAnswer.updated_at.asc())
        ):
            answers_by_run[answer.run_id].append(answer)
    masterclass_events = list(
        db.scalars(
            select(MasterclassEvent)
            .where(MasterclassEvent.user_id == user_id)
            .order_by(MasterclassEvent.occurred_at.desc())
            .limit(50)
        )
    )
    masterclass_offers = list(
        db.scalars(
            select(UserOffer)
            .where(UserOffer.user_id == user_id)
            .order_by(UserOffer.started_at.desc())
            .limit(10)
        )
    )
    question_titles = {
        kind: {code: title for code, title, _ in rows}
        for kind, rows in {
            "onboarding": ONBOARDING_QUESTIONS,
            "current-diet": CURRENT_DIET_QUESTIONS,
            "closing-review": CLOSING_QUESTIONS,
        }.items()
    }
    paid = [payment for payment, _, _ in payments if payment.payment_status in CONFIRMED_PAYMENT_STATUSES]
    actual_paid = [payment for payment in paid if not payment.amount_is_estimated]
    estimated_paid = [payment for payment in paid if payment.amount_is_estimated]
    return {
        "id": str(user.id),
        "display_name": user.display_name,
        "status": user.status,
        "data_origin": user.data_origin,
        "first_seen_at": user.first_seen_at,
        "access_review_status": user.access_review_status,
        "access_review_note": user.access_review_note,
        "tilda_access_status": user.tilda_access_status,
        "tilda_membership": {
            "groups": list((tilda_snapshot.raw_payload or {}).get("groups", [])),
            "account_status": (tilda_snapshot.raw_payload or {}).get("account_status"),
            "member_created_at": (tilda_snapshot.raw_payload or {}).get("member_created_at"),
            "last_active_at": (tilda_snapshot.raw_payload or {}).get("last_active_at"),
            "source": tilda_snapshot.source,
        } if tilda_snapshot else None,
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
                "subscription_status": item.subscription_status,
                "main_scenario_seen_at": item.main_scenario_seen_at,
            }
            for item in messengers
        ],
        "phones": [
            {"phone": item.phone_original, "primary": item.is_primary, "source": item.source}
            for item in phones
        ],
        "purchase_count": len(paid),
        "ltv_rub": money(sum((payment.amount for payment in actual_paid if payment.currency == "RUB" and payment.amount is not None), Decimal())),
        "estimated_ltv_rub": money(sum((payment.amount for payment in estimated_paid if payment.currency == "RUB" and payment.amount is not None), Decimal())),
        "total_ltv_rub": money(sum((payment.amount for payment in paid if payment.currency == "RUB" and payment.amount is not None), Decimal())),
        "payments": [
            {
                "id": str(payment.id),
                "product_code": product_code,
                "product_name": product_name,
                "product_name_raw": payment.product_name_raw,
                "tariff": tariff_name(db, product_code),
                "amount": money(payment.amount) if payment.amount is not None else None,
                "amount_is_estimated": payment.amount_is_estimated,
                "currency": payment.currency,
                "status": payment.payment_status,
                "review_status": payment.review_status,
                "paid_at": payment.paid_at,
                "source_event_at": payment.source_event_at,
            }
            for payment, product_code, product_name in payments
        ],
        "purchased_products": purchased_products(db, user.id),
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
        "masterclass": {
            "questionnaires": [
                {
                    "kind": run.kind,
                    "status": run.status,
                    "submitted_at": run.submitted_at,
                    "answers": [
                        {
                            "code": answer.question_code,
                            "title": question_titles.get(run.kind, {}).get(answer.question_code, answer.question_code),
                            "answer": answer.answer_text,
                            "updated_at": answer.updated_at,
                        }
                        for answer in answers_by_run.get(run.id, [])
                    ],
                }
                for run in questionnaire_runs
            ],
            "events": [
                {
                    "type": event.event_type,
                    "placement": event.placement,
                    "occurred_at": event.occurred_at,
                }
                for event in masterclass_events
            ],
            "offers": [
                {
                    "stage": offer.stage_code,
                    "status": offer.status,
                    "started_at": offer.started_at,
                    "expires_at": offer.expires_at,
                }
                for offer in masterclass_offers
            ],
        },
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
    "content",
    "funnel",
    "intensive",
    "obsolete",
    "purchase",
    "routing",
    "tariff",
    "access_hint",
    "review",
    "content_review",
    "refund",
}
TAG_STATUSES = {"active", "archived", "review", "merged"}


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
                t.audit_action,
                t.audit_reason,
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
            "audit_action": row["audit_action"],
            "audit_reason": row["audit_reason"],
        }
        for row in rows
    ]


def update_tag(
    db: Session, tag_id: uuid.UUID, name: str, category: str, status: str
) -> bool:
    if category not in TAG_CATEGORIES or status not in {"active", "archived", "review"}:
        return False
    result = db.execute(
        text(
            """
            UPDATE tags
            SET name = :name, category = :category, status = :status,
                merged_into_tag_id = CASE WHEN :status IN ('active','review') THEN NULL ELSE merged_into_tag_id END,
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


def list_access_reviews(db: Session, limit: int = 1000) -> list[dict]:
    email, telegram, purchases, _, _ = _user_scalar_subqueries()
    rows = db.execute(
        select(
            User.id, User.display_name, User.access_review_status, User.access_review_note,
            User.tilda_access_status, email.label("email"), telegram.label("telegram"),
            purchases.label("purchase_count"),
        )
        .where(User.merged_into_user_id.is_(None), User.access_review_status != "not_required")
        .order_by(User.updated_at.desc())
        .limit(min(max(limit, 1), 1000))
    ).mappings().all()
    return [{**dict(row), "id": str(row["id"]), "purchase_count": row["purchase_count"] or 0} for row in rows]


def list_resources(db: Session) -> list[dict]:
    return [{"code": item.code, "name": item.name} for item in db.scalars(
        select(Resource).where(Resource.status == "active").order_by(Resource.name)
    )]


def link_user_email(db: Session, user_id: uuid.UUID, email: str, admin: str) -> tuple[bool, str]:
    normalized = email.strip().lower()
    if "@" not in normalized or len(normalized) > 320:
        return False, "invalid_email"
    user = db.get(User, user_id)
    if user is None or user.merged_into_user_id is not None:
        return False, "user_not_found"
    existing = db.scalar(select(UserEmail).where(UserEmail.email_normalized == normalized))
    if existing and existing.user_id != user_id:
        user.access_review_status = "conflict"
        user.access_review_note = f"Email уже связан с другим user_id: {normalized}"
        db.commit()
        return False, "email_conflict"
    if existing is None:
        db.add(UserEmail(user_id=user_id, email_original=email.strip(), email_normalized=normalized,
                         is_primary=True, verification_status="owner_confirmed", source="manual_admin",
                         first_seen_at=datetime.now(timezone.utc)))
    user.access_review_status = "pending"
    db.add(AdminAppEdit(admin_username=admin, target_user_id=user_id, app_code="crm",
                        action="link_email", details={"email": normalized}))
    db.commit()
    return True, "linked"


def set_access_review(db: Session, user_id: uuid.UUID, status: str, tilda_status: str,
                      note: str | None, admin: str) -> bool:
    if status not in {"waiting_registration", "pending", "completed", "conflict", "not_required"}:
        return False
    if tilda_status not in {"not_checked", "pending", "granted", "not_required"}:
        return False
    user = db.get(User, user_id)
    if user is None or user.merged_into_user_id is not None:
        return False
    user.access_review_status = status
    user.tilda_access_status = tilda_status
    user.access_review_note = (note or "").strip() or None
    user.access_reviewed_at = datetime.now(timezone.utc) if status == "completed" else None
    db.add(AdminAppEdit(admin_username=admin, target_user_id=user_id, app_code="crm",
                        action="access_review", details={"status": status, "tilda": tilda_status}))
    db.commit()
    return True


def grant_manual_access(db: Session, user_id: uuid.UUID, resource_code: str, admin: str) -> bool:
    user = db.get(User, user_id)
    resource = db.scalar(select(Resource).where(Resource.code == resource_code))
    if user is None or resource is None:
        return False
    active = db.scalar(select(UserAccess).where(UserAccess.user_id == user_id,
        UserAccess.resource_id == resource.id, UserAccess.revoked_at.is_(None)))
    if active is None:
        db.add(UserAccess(user_id=user_id, resource_id=resource.id, source_payment_id=None,
                          source="manual_admin", granted_at=datetime.now(timezone.utc)))
    db.add(AdminAppEdit(admin_username=admin, target_user_id=user_id, app_code="crm",
                        action="grant_access", details={"resource_code": resource_code}))
    db.commit()
    return True


def revoke_manual_access(db: Session, user_id: uuid.UUID, resource_code: str, admin: str) -> bool:
    access = db.scalar(select(UserAccess).join(Resource).where(UserAccess.user_id == user_id,
        Resource.code == resource_code, UserAccess.revoked_at.is_(None)).order_by(UserAccess.granted_at.desc()))
    if access is None:
        return False
    access.revoked_at = datetime.now(timezone.utc)
    db.add(AdminAppEdit(admin_username=admin, target_user_id=user_id, app_code="crm",
                        action="revoke_access", details={"resource_code": resource_code}))
    db.commit()
    return True
