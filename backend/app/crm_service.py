from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Uuid, bindparam, case, distinct, exists, func, or_, select, text, update
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
    RecurringSubscription,
    UserOffer,
    AccountCredential,
    AccountSession,
    CourseStageProgress,
    DqsState,
    MasterclassDayProgress,
    UserCoursePolicy,
)
from app.account_security import decrypt_password, encrypt_password, generate_password, password_hash
from app.account_onboarding_service import queue_direct_credential_email
from app.app_service import EMAIL_RE, normalize_email
from app.config import Settings
from app.masterclass_routes import (
    questions,
)
from app.product_identity import purchased_products, tariff_label
from app.course_access_service import set_course_unlock_mode

CONFIRMED_PAYMENT_STATUSES = ("paid", "confirmed")
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
COURSE_RESOURCE_CODES = (
    "ACCESS_MASTERCLASS",
    "ACCESS_RECIPES",
    "ACCESS_CALORIES",
    "ACCESS_STRENGTH",
)
APP_RESOURCE_CODES = ("dqs", "strength", "metabolism")


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
    first_purchase = (
        select(func.min(func.coalesce(Payment.paid_at, Payment.source_event_at, Payment.created_at)))
        .where(Payment.user_id == User.id, Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES))
        .correlate(User)
        .scalar_subquery()
    )
    last_purchase = (
        select(func.max(Payment.paid_at))
        .where(Payment.user_id == User.id, Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES))
        .correlate(User)
        .scalar_subquery()
    )
    return email, telegram, purchases, actual_ltv, estimated_ltv, first_purchase, last_purchase


def list_users(
    db: Session,
    query: str = "",
    buyers_only: bool = False,
    buyer_kind: str = "all", product_code: str = "", first_seen_from: date | None = None,
    first_seen_to: date | None = None, masterclass_access: bool | None = None,
    accompaniment_status: str = "all", tag_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    email, telegram, purchases, actual_ltv, estimated_ltv, first_purchase, last_purchase = _user_scalar_subqueries()
    initial_product_code = (
        select(Product.code)
        .join(Payment, Payment.product_id == Product.id)
        .where(
            Payment.user_id == User.id,
            Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES),
        )
        .order_by(func.coalesce(Payment.paid_at, Payment.source_event_at, Payment.created_at).asc())
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )
    first_source = (
        select(func.coalesce(AttributionEvent.utm_source, AttributionEvent.source_raw))
        .where(
            AttributionEvent.user_id == User.id,
            or_(
                AttributionEvent.utm_source.is_not(None),
                AttributionEvent.source_raw.is_not(None),
            ),
        )
        .order_by(
            AttributionEvent.occurred_at.asc().nullslast(),
            AttributionEvent.created_at.asc(),
        )
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )
    active_accompaniment = exists(
        select(RecurringSubscription.id).where(
            RecurringSubscription.user_id == User.id,
            RecurringSubscription.product_code == "COACHING",
            RecurringSubscription.status.in_(("active", "charging")),
        )
    )
    paid_accompaniment = exists(
        select(RecurringSubscription.id).where(
            RecurringSubscription.user_id == User.id,
            RecurringSubscription.product_code == "COACHING",
            RecurringSubscription.successful_payments > 0,
            RecurringSubscription.status != "test_paid",
        )
    )
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
            first_purchase.label("first_purchase_at"),
            last_purchase.label("last_purchase_at"),
            initial_product_code.label("initial_product_code"),
            first_source.label("first_source"),
            case(
                (active_accompaniment, "active"),
                (paid_accompaniment, "former"),
                else_="none",
            ).label("accompaniment_status"),
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
        access_exists = exists(select(UserAccess.id).join(Resource, Resource.id == UserAccess.resource_id).where(UserAccess.user_id == User.id, Resource.code == "ACCESS_MASTERCLASS", UserAccess.revoked_at.is_(None), UserAccess.paused_at.is_(None), or_(UserAccess.expires_at.is_(None), UserAccess.expires_at > func.now())))
        stmt = stmt.where(access_exists if masterclass_access else ~access_exists)
    if accompaniment_status == "active":
        stmt = stmt.where(active_accompaniment)
    elif accompaniment_status == "former":
        stmt = stmt.where(paid_accompaniment, ~active_accompaniment)
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
    tariff_by_product_code = {
        code: tariff_label(db, code)
        for code in {row["initial_product_code"] for row in rows if row["initial_product_code"]}
    }
    user_ids = [row["id"] for row in rows]
    access_by_user: dict[uuid.UUID, list[str]] = {user_id: [] for user_id in user_ids}
    messengers_by_user: dict[uuid.UUID, list[dict]] = {
        user_id: [] for user_id in user_ids
    }
    note_count_by_user: dict[uuid.UUID, int] = {user_id: 0 for user_id in user_ids}
    if user_ids:
        access_rows = db.execute(
            select(UserAccess.user_id, Resource.code)
            .join(Resource, Resource.id == UserAccess.resource_id)
            .where(
                UserAccess.user_id.in_(user_ids),
                UserAccess.revoked_at.is_(None),
                UserAccess.paused_at.is_(None),
                or_(UserAccess.expires_at.is_(None), UserAccess.expires_at > func.now()),
            )
            .distinct()
            .order_by(Resource.code)
        ).all()
        for user_id, code in access_rows:
            access_by_user[user_id].append(code)
        messenger_rows = db.execute(
            select(
                MessengerAccount.user_id,
                MessengerAccount.platform,
                MessengerAccount.platform_user_id,
                MessengerAccount.username,
                MessengerAccount.first_seen_at,
                MessengerAccount.last_seen_at,
                MessengerAccount.main_scenario_seen_at,
                MessengerAccount.subscription_status,
            )
            .where(MessengerAccount.user_id.in_(user_ids))
            .order_by(MessengerAccount.created_at.asc())
        ).mappings().all()
        for messenger in messenger_rows:
            messengers_by_user[messenger["user_id"]].append(
                {
                    "platform": messenger["platform"],
                    "platform_user_id": messenger["platform_user_id"],
                    "username": messenger["username"],
                    "first_seen_at": messenger["first_seen_at"],
                    "last_seen_at": messenger["last_seen_at"],
                    "main_scenario_seen_at": messenger["main_scenario_seen_at"],
                    "subscription_status": messenger["subscription_status"],
                }
            )
        note_rows = db.execute(
            select(ClientNote.user_id, func.count(ClientNote.id))
            .where(ClientNote.user_id.in_(user_ids))
            .group_by(ClientNote.user_id)
        ).all()
        for user_id, note_count in note_rows:
            note_count_by_user[user_id] = note_count
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
            "first_purchase_at": row["first_purchase_at"],
            "last_purchase_at": row["last_purchase_at"],
            "initial_tariff": tariff_by_product_code.get(row["initial_product_code"]),
            "first_source": row["first_source"],
            "accompaniment_status": row["accompaniment_status"],
            "first_seen_at": row["first_seen_at"],
            "access_review_status": row["access_review_status"],
            "tilda_access_status": row["tilda_access_status"],
            "accesses": access_by_user[row["id"]],
            "messengers": messengers_by_user[row["id"]],
            "note_count": note_count_by_user[row["id"]],
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
    offset: int = 0,
    snapshot_at: datetime | None = None,
    query: str = "",
    product_code: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    amount_kind: str = "all",
) -> list[dict]:
    snapshot = snapshot_at or datetime.now(timezone.utc)
    if snapshot.tzinfo is None:
        snapshot = snapshot.replace(tzinfo=timezone.utc)
    stmt = (
        select(Payment, User.display_name, Product.code, Product.name)
        .outerjoin(User, User.id == Payment.user_id)
        .outerjoin(Product, Product.id == Payment.product_id)
        .order_by(Payment.source_event_at.desc().nullslast(), Payment.created_at.desc(), Payment.id.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 500))
        .where(Payment.created_at <= snapshot)
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
            "source": payment.source,
            "payment_system": payment.payment_system,
            "external_order_id": payment.external_order_id,
            "paid_at": payment.paid_at,
            "source_event_at": payment.source_event_at,
            "snapshot_at": snapshot,
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
    active_access_codes = {
        code
        for access, code, _ in accesses
        if access.revoked_at is None
        and access.paused_at is None
        and (access.expires_at is None or access.expires_at > datetime.now(timezone.utc))
    }
    masterclass_progress = list(
        db.scalars(
            select(MasterclassDayProgress)
            .where(MasterclassDayProgress.user_id == user_id)
            .order_by(MasterclassDayProgress.day_number.asc())
        )
    )
    calorie_progress = list(
        db.scalars(
            select(CourseStageProgress)
            .where(
                CourseStageProgress.user_id == user_id,
                CourseStageProgress.course_code == "calories",
            )
            .order_by(CourseStageProgress.stage_number.asc())
        )
    )
    dqs_state = db.scalar(select(DqsState).where(DqsState.user_id == user_id))
    active_coaching = bool(
        db.scalar(
            select(
                exists(
                    select(RecurringSubscription.id).where(
                        RecurringSubscription.user_id == user_id,
                        RecurringSubscription.product_code == "COACHING",
                        RecurringSubscription.status.in_(("active", "charging")),
                    )
                )
            )
        )
    )
    paid_coaching = bool(
        db.scalar(
            select(
                exists(
                    select(RecurringSubscription.id).where(
                        RecurringSubscription.user_id == user_id,
                        RecurringSubscription.product_code == "COACHING",
                        RecurringSubscription.successful_payments > 0,
                        RecurringSubscription.status != "test_paid",
                    )
                )
            )
        )
    )
    product_progress: list[dict] = []
    if "ACCESS_MASTERCLASS" in active_access_codes:
        completed = sum(item.completed_at is not None for item in masterclass_progress)
        legacy_complete = bool(tilda_snapshot and not masterclass_progress)
        product_progress.append(
            {
                "code": "masterclass",
                "name": "Мастер-класс",
                "completed": 20 if legacy_complete else completed,
                "total": 20,
                "percent": 100 if legacy_complete else round(completed / 20 * 100),
                "legacy_assumed_complete": legacy_complete,
            }
        )
    if "ACCESS_CALORIES" in active_access_codes:
        completed = sum(item.completed_at is not None for item in calorie_progress)
        legacy_complete = bool(tilda_snapshot and not calorie_progress)
        product_progress.append(
            {
                "code": "calories",
                "name": "Калорийный курс",
                "completed": 5 if legacy_complete else completed,
                "total": 5,
                "percent": 100 if legacy_complete else round(completed / 5 * 100),
                "legacy_assumed_complete": legacy_complete,
            }
        )
    if "ACCESS_DQS" in active_access_codes:
        completed = min(len(dqs_state.days or {}), 30) if dqs_state is not None else 0
        legacy_complete = bool(tilda_snapshot and dqs_state is None)
        product_progress.append(
            {
                "code": "dqs",
                "name": "Diet Quality Score",
                "completed": 30 if legacy_complete else completed,
                "total": 30,
                "percent": 100 if legacy_complete else round(completed / 30 * 100),
                "legacy_assumed_complete": legacy_complete,
            }
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
    credential = db.get(AccountCredential, user_id)
    question_titles = {
        kind: {code: title for code, title, _ in rows}
        for kind, rows in {
            "onboarding": questions("onboarding", db),
            "current-diet": questions("current-diet", db),
            "closing-review": questions("closing-review", db),
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
        "accompaniment_status": "active" if active_coaching else "former" if paid_coaching else "none",
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
        "product_progress": product_progress,
        "emails": [
            {
                "email": item.email_original,
                "primary": item.is_primary,
                "verification_status": item.verification_status,
            }
            for item in emails
        ],
        "credential": {
            "exists": credential is not None,
            "password_available": bool(credential and credential.password_ciphertext),
            "password_version": credential.password_version if credential else None,
            "issued_via": credential.issued_via if credential else None,
            "updated_at": credential.updated_at if credential else None,
        },
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
                "tariff": tariff_label(db, product_code),
                "amount": money(payment.amount) if payment.amount is not None else None,
                "amount_is_estimated": payment.amount_is_estimated,
                "currency": payment.currency,
                "status": payment.payment_status,
                "review_status": payment.review_status,
                "source": payment.source,
                "payment_system": payment.payment_system,
                "external_order_id": payment.external_order_id,
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
                "paused_at": access.paused_at,
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
    email, telegram, purchases, _, _, _, _ = _user_scalar_subqueries()
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


def course_access_states(db: Session, user_id: uuid.UUID) -> list[dict]:
    """Current availability settings for the four course products in CRM."""
    resource_rows = {
        item.code: item
        for item in db.scalars(
            select(Resource).where(Resource.code.in_(COURSE_RESOURCE_CODES), Resource.status == "active")
        )
    }
    now = datetime.now(timezone.utc)
    active_codes = set(
        db.scalars(
            select(Resource.code)
            .join(UserAccess, UserAccess.resource_id == Resource.id)
            .where(
                UserAccess.user_id == user_id,
                Resource.code.in_(COURSE_RESOURCE_CODES),
                UserAccess.revoked_at.is_(None),
                UserAccess.paused_at.is_(None),
                UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now),
            )
        )
    )
    policies = {
        resource_code: (unlock_mode, start_mode)
        for resource_code, unlock_mode, start_mode in db.execute(
            select(Resource.code, UserCoursePolicy.unlock_mode, UserCoursePolicy.start_mode)
            .join(Resource, Resource.id == UserCoursePolicy.resource_id)
            .where(UserCoursePolicy.user_id == user_id, Resource.code.in_(COURSE_RESOURCE_CODES))
        )
    }
    names = {
        "ACCESS_MASTERCLASS": "Мастер-класс",
        "ACCESS_RECIPES": "Система рецептов",
        "ACCESS_CALORIES": "Калорийный курс",
        "ACCESS_STRENGTH": "Курс тренировок",
    }
    return [
        {
            "resource_code": code,
            "name": names[code],
            "available": code in resource_rows,
            "entitled": code in active_codes,
            # Existing rows without the new policy retain their established
            # behaviour and are immediately startable.
            "start_open": code in active_codes and policies.get(code, ("paced", "open"))[1] == "open",
            "all_lessons_open": code in active_codes and policies.get(code, ("paced", "open"))[0] == "fully_unlocked",
        }
        for code in COURSE_RESOURCE_CODES
    ]


def update_course_access_state(
    db: Session,
    user_id: uuid.UUID,
    resource_code: str,
    *,
    entitled: bool,
    start_open: bool,
    all_lessons_open: bool,
    admin: str,
) -> list[dict]:
    if resource_code not in COURSE_RESOURCE_CODES:
        raise ValueError("unknown_course")
    if all_lessons_open and not start_open:
        raise ValueError("all_lessons_requires_start")
    if (start_open or all_lessons_open) and not entitled:
        raise ValueError("course_state_requires_right")
    user = db.get(User, user_id)
    resource = db.scalar(
        select(Resource).where(Resource.code == resource_code, Resource.status == "active")
    )
    if user is None or user.merged_into_user_id is not None or resource is None:
        raise ValueError("user_or_resource_not_found")
    now = datetime.now(timezone.utc)
    rows = list(
        db.scalars(
            select(UserAccess).where(
                UserAccess.user_id == user_id,
                UserAccess.resource_id == resource.id,
                UserAccess.revoked_at.is_(None),
            )
        )
    )
    if entitled:
        usable = [item for item in rows if item.expires_at is None or item.expires_at > now]
        if usable:
            for item in usable:
                item.paused_at = None
        else:
            db.add(UserAccess(
                user_id=user_id,
                resource_id=resource.id,
                source_payment_id=None,
                source="manual_admin",
                granted_at=now,
            ))
        policy = db.scalar(
            select(UserCoursePolicy).where(
                UserCoursePolicy.user_id == user_id,
                UserCoursePolicy.resource_id == resource.id,
            )
        )
        if policy is None:
            db.add(UserCoursePolicy(
                user_id=user_id,
                resource_id=resource.id,
                unlock_mode="fully_unlocked" if all_lessons_open else "paced",
                start_mode="open" if start_open else "auto",
                source="manual_admin",
            ))
        else:
            policy.unlock_mode = "fully_unlocked" if all_lessons_open else "paced"
            policy.start_mode = "open" if start_open else "auto"
            policy.source = "manual_admin"
    else:
        # Do not erase a payment record: pausing makes the right unavailable
        # now but preserves purchase history and lets an administrator resume it.
        for item in rows:
            item.paused_at = now
    db.add(AdminAppEdit(
        admin_username=admin,
        target_user_id=user_id,
        app_code="crm",
        action="set_course_access_state",
        details={
            "resource_code": resource_code,
            "entitled": entitled,
            "start_open": start_open,
            "all_lessons_open": all_lessons_open,
        },
    ))
    db.commit()
    return course_access_states(db, user_id)


def set_manual_course_policy(
    db: Session,
    user_id: uuid.UUID,
    resource_code: str,
    unlock_mode: str,
    admin: str,
) -> tuple[bool, str]:
    """Compatibility adapter for the former one-setting CRM endpoint."""
    before = db.scalar(
        select(UserCoursePolicy.unlock_mode)
        .join(Resource, Resource.id == UserCoursePolicy.resource_id)
        .where(
            UserCoursePolicy.user_id == user_id,
            Resource.code == resource_code,
        )
    ) or "paced"
    ok, result = set_course_unlock_mode(
        db, user_id, resource_code, unlock_mode, source="manual_admin"
    )
    if not ok:
        return False, result
    # The former endpoint has one combined setting. A full unlock is an
    # immediate entry override; returning to paced restores the ordinary gate.
    policy = db.scalar(
        select(UserCoursePolicy)
        .join(Resource, Resource.id == UserCoursePolicy.resource_id)
        .where(
            UserCoursePolicy.user_id == user_id,
            Resource.code == resource_code,
        )
    )
    if policy is not None:
        policy.start_mode = "open" if unlock_mode == "fully_unlocked" else "auto"
    db.add(
        AdminAppEdit(
            admin_username=admin,
            target_user_id=user_id,
            app_code="crm",
            action="set_course_unlock_mode",
            details={
                "resource_code": resource_code,
                "before": before,
                "after": unlock_mode,
            },
        )
    )
    db.commit()
    return True, result


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
    else:
        active.paused_at = None
    db.add(AdminAppEdit(admin_username=admin, target_user_id=user_id, app_code="crm",
                        action="grant_access", details={"resource_code": resource_code}))
    db.commit()
    return True


def revoke_manual_access(db: Session, user_id: uuid.UUID, resource_code: str, admin: str) -> bool:
    accesses = list(db.scalars(select(UserAccess).join(Resource).where(UserAccess.user_id == user_id,
        Resource.code == resource_code, UserAccess.revoked_at.is_(None))))
    if not accesses:
        return False
    now = datetime.now(timezone.utc)
    for access in accesses:
        access.revoked_at = now
        access.paused_at = None
    db.add(AdminAppEdit(admin_username=admin, target_user_id=user_id, app_code="crm",
                        action="revoke_access", details={"resource_code": resource_code}))
    db.commit()
    return True


def pause_manual_access(db: Session, user_id: uuid.UUID, resource_code: str, admin: str) -> bool:
    accesses = list(db.scalars(select(UserAccess).join(Resource).where(
        UserAccess.user_id == user_id,
        Resource.code == resource_code,
        UserAccess.revoked_at.is_(None),
    )))
    if not accesses:
        return False
    now = datetime.now(timezone.utc)
    for access in accesses:
        access.paused_at = now
    db.add(AdminAppEdit(admin_username=admin, target_user_id=user_id, app_code="crm",
                        action="pause_access", details={"resource_code": resource_code}))
    db.commit()
    return True


def resume_manual_access(db: Session, user_id: uuid.UUID, resource_code: str, admin: str) -> bool:
    accesses = list(db.scalars(select(UserAccess).join(Resource).where(
        UserAccess.user_id == user_id,
        Resource.code == resource_code,
        UserAccess.revoked_at.is_(None),
        UserAccess.paused_at.is_not(None),
    )))
    if not accesses:
        return False
    for access in accesses:
        access.paused_at = None
    db.add(AdminAppEdit(admin_username=admin, target_user_id=user_id, app_code="crm",
                        action="resume_access", details={"resource_code": resource_code}))
    db.commit()
    return True


def set_manual_app_access(
    db: Session,
    user_id: uuid.UUID,
    resource_code: str,
    *,
    enabled: bool,
    admin: str,
) -> bool:
    """Toggle one standalone app right without changing any course right."""
    if resource_code not in APP_RESOURCE_CODES:
        return False
    user = db.get(User, user_id)
    resource = db.scalar(
        select(Resource).where(Resource.code == resource_code, Resource.status == "active")
    )
    if user is None or user.merged_into_user_id is not None or resource is None:
        return False
    now = datetime.now(timezone.utc)
    rows = list(db.scalars(select(UserAccess).where(
        UserAccess.user_id == user_id,
        UserAccess.resource_id == resource.id,
    )))
    if enabled:
        # A prior manually/imported standalone-app row can be safely reused.
        # It keeps the unique user/resource/manual row stable and does not touch
        # a course resource such as ACCESS_CALORIES.
        reusable = next((item for item in rows if item.source_payment_id is None), None)
        if reusable is None:
            db.add(UserAccess(
                user_id=user_id,
                resource_id=resource.id,
                source_payment_id=None,
                source="manual_admin",
                granted_at=now,
            ))
        else:
            reusable.revoked_at = None
            reusable.paused_at = None
            reusable.expires_at = None
    else:
        # Closing a checkbox only pauses the standalone manual row created by
        # this control.  It must never take a paid right away and never touch
        # a course resource that may independently open an application.
        for item in rows:
            if item.source_payment_id is None and item.revoked_at is None:
                item.paused_at = now
    db.add(AdminAppEdit(
        admin_username=admin,
        target_user_id=user_id,
        app_code="crm",
        action="set_manual_app_access",
        details={"resource_code": resource_code, "enabled": enabled},
    ))
    db.commit()
    return True


def reveal_account_password(
    db: Session, user_id: uuid.UUID, settings: Settings, admin: str
) -> str | None:
    user = db.get(User, user_id)
    credential = db.get(AccountCredential, user_id)
    if user is None or user.merged_into_user_id is not None or credential is None:
        return None
    if not credential.password_ciphertext:
        raise ValueError("legacy_password")
    password = decrypt_password(credential.password_ciphertext, settings.app_auth_secret)
    db.add(AdminAppEdit(admin_username=admin, target_user_id=user_id, app_code="crm",
                        action="reveal_account_password", details={"password_version": credential.password_version}))
    db.commit()
    return password


def _issue_account_password(
    db: Session, user: User, settings: Settings, admin: str
) -> tuple[str, AccountCredential]:
    password = generate_password()
    credential = db.get(AccountCredential, user.id)
    if credential is None:
        credential = AccountCredential(
            user_id=user.id,
            password_hash=password_hash(password, settings.app_auth_secret),
            password_ciphertext=encrypt_password(password, settings.app_auth_secret),
            password_version=1,
            issued_via="admin",
        )
        db.add(credential)
    else:
        credential.password_hash = password_hash(password, settings.app_auth_secret)
        credential.password_ciphertext = encrypt_password(password, settings.app_auth_secret)
        credential.password_version += 1
        credential.issued_via = "admin"
    now = datetime.now(timezone.utc)
    db.execute(update(AccountSession).where(
        AccountSession.user_id == user.id,
        AccountSession.revoked_at.is_(None),
    ).values(revoked_at=now))
    db.flush()
    db.add(AdminAppEdit(admin_username=admin, target_user_id=user.id, app_code="crm",
                        action="reset_account_password", details={"password_version": credential.password_version}))
    return password, credential


def reset_account_password(
    db: Session, user_id: uuid.UUID, settings: Settings, admin: str
) -> str | None:
    user = db.get(User, user_id)
    if user is None or user.merged_into_user_id is not None:
        return None
    password, _ = _issue_account_password(db, user, settings, admin)
    db.commit()
    return password


def create_manual_account(
    db: Session, *, email_original: str, display_name: str | None, settings: Settings, admin: str
) -> tuple[User, str]:
    """Create a no-access CRM person, issue a password and queue its email.

    This intentionally does not invent a purchase. Course rights are set from
    the newly created card, before the person ever signs in.
    """
    email = normalize_email(email_original)
    if not EMAIL_RE.match(email):
        raise ValueError("invalid_email")
    existing = db.scalar(select(UserEmail).where(UserEmail.email_normalized == email))
    if existing is not None:
        raise ValueError("email_exists")
    now = datetime.now(timezone.utc)
    user = User(
        display_name=(display_name or "").strip() or None,
        status="active",
        data_origin="native",
        first_seen_at=now,
        access_review_status="not_required",
        tilda_access_status="not_required",
    )
    db.add(user)
    db.flush()
    db.add(UserEmail(
        user_id=user.id,
        email_original=email_original.strip(),
        email_normalized=email,
        is_primary=True,
        verification_status="owner_confirmed",
        source="manual_admin",
        first_seen_at=now,
    ))
    password, credential = _issue_account_password(db, user, settings, admin)
    email_row = queue_direct_credential_email(
        db,
        user=user,
        password_version=credential.password_version,
        settings=settings,
    )
    db.add(AdminAppEdit(
        admin_username=admin,
        target_user_id=user.id,
        app_code="crm",
        action="create_manual_account",
        details={"email": email, "email_delivery": "queued", "onboarding_id": str(email_row.id)},
    ))
    db.commit()
    return user, password
