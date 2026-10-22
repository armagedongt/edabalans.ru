"""Observed financial facts; calendar receipts and entry cohorts stay separate."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import re
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.finance_plans import private, write_guard
from app.managed_documents import document_hash
from app.marketing_service import _canonical_user_map, _is_confirmed_bot_start, _attribution_values
from app.models import (AttributionEvent, ManagedDocumentVersion, MessengerAccount,
                        Payment, PriceEntry, Product, TelegramTrackingEvent, TelegramTrackingLink, User)
from app.payment_metrics import CONFIRMED_PAYMENT_STATUSES, coaching_payment_summary, is_coaching_payment

MOSCOW = ZoneInfo("Europe/Moscow")
OBSERVATION_START = date(2026, 9, 1)
EXPENSE_TYPE = "finance-month-expenses"
router = APIRouter(prefix="/admin/api/finance", dependencies=[Depends(require_admin), Depends(private)])


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def month_date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise HTTPException(422, "Месяц должен быть в формате ГГГГ-ММ")
    try:
        return date.fromisoformat(value + "-01")
    except ValueError:
        raise HTTPException(422, "Некорректный месяц") from None


def next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def period(month: str | None, now: datetime):
    start = month_date(month) if month else OBSERVATION_START
    if start < OBSERVATION_START or start > now.astimezone(MOSCOW).date().replace(day=1):
        raise HTTPException(422, "Выберите месяц с сентября 2026 до текущего")
    end = min(datetime.combine(next_month(start), time(), MOSCOW), now) if month else now
    return datetime.combine(start, time(), MOSCOW), end


class ExpenseIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    month: str
    ads: float | None = Field(default=None, ge=0, le=1e9, strict=True)
    opex: float | None = Field(default=None, ge=0, le=1e9, strict=True)


@router.post("/expenses", dependencies=[Depends(write_guard)])
def save_expenses(body: ExpenseIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    period(body.month, datetime.now(timezone.utc))
    payload = body.model_dump()
    db.add(ManagedDocumentVersion(document_type=EXPENSE_TYPE, document_key=str(uuid.uuid4()),
        schema_version=1, version_no=1, payload=payload, content_hash=document_hash(payload),
        created_by=admin, created_at=datetime.now(timezone.utc), is_active=True))
    db.commit()
    return {"saved": True}


def expense_totals(db, start, end):
    snapshots = db.scalars(select(ManagedDocumentVersion).where(
        ManagedDocumentVersion.document_type == EXPENSE_TYPE,
        ManagedDocumentVersion.is_active.is_(True)).order_by(
            ManagedDocumentVersion.created_at.desc(), ManagedDocumentVersion.id.desc()))
    latest = {}
    for row in snapshots:
        latest.setdefault(row.payload["month"], row.payload)
    months = []
    current = start.date().replace(day=1)
    while datetime.combine(current, time(), MOSCOW) < end:
        months.append(current.strftime("%Y-%m"))
        current = next_month(current)
    def total(key):
        values = [latest.get(month, {}).get(key) for month in months]
        return sum(values) if values and all(value is not None for value in values) else None
    return {"ads": total("ads"), "opex": total("opex"),
            "months_total": len(months),
            "months_recorded": sum(month in latest for month in months)}


def acquisition(event, link):
    medium = _attribution_values(event, link)["placement"].lower().strip()
    if medium in {"cpc", "cpm", "cpa", "paid", "paid_social", "paid_post"}:
        return "paid"
    if medium in {"organic", "organic_post", "owned", "referral"}:
        return "organic"
    return "unknown"


def report(db: Session, month: str | None, now: datetime | None = None) -> dict:
    now = aware(now or datetime.now(timezone.utc))
    start, end = period(month, now)
    observation_start = datetime.combine(OBSERVATION_START, time(), MOSCOW)
    users = list(db.scalars(select(User)))
    canonical = _canonical_user_map(users)
    def person(uid):
        return "user:" + canonical.get(str(uid), str(uid))
    names = {person(user.id): user.display_name or "Без имени" for user in users
             if user.merged_into_user_id is None}
    accounts = {(account.platform, str(account.platform_user_id)): person(account.user_id)
                for account in db.scalars(select(MessengerAccount))}
    links = {link.id: link for link in db.scalars(select(TelegramTrackingLink))}
    entries = {}
    def record(event, platform, link=None):
        identity = person(event.user_id) if event.user_id else accounts.get((platform, str(event.telegram_user_id)))
        if not identity and getattr(event, "telegram_user_id", None):
            identity = platform + ":" + str(event.telegram_user_id)
        if not identity or not event.occurred_at:
            return
        at = aware(event.occurred_at)
        if at > now:
            return
        if identity not in entries or at < entries[identity]["at"]:
            entries[identity] = {"at": at, "source": acquisition(event, link)}
        elif at == entries[identity]["at"] and entries[identity]["source"] == "unknown":
            # Membership and tracked join can be two observations of one transaction.
            entries[identity]["source"] = acquisition(event, link)
    for event in db.scalars(select(TelegramTrackingEvent)):
        metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        joined = event.event_type == "channel_join" or (event.event_type == "channel_membership"
                   and metadata.get("subscribed") is True and metadata.get("joined") is True)
        if joined or _is_confirmed_bot_start(event):
            record(event, metadata.get("messenger", "telegram"), links.get(event.tracking_link_id))
    for event in db.scalars(select(AttributionEvent)):
        if event.user_id and event.occurred_at and _is_confirmed_bot_start(event):
            record(event, "max" if event.event_type.startswith("max_") else "telegram")

    raw_rows = db.execute(select(Payment, func.coalesce(Product.code, PriceEntry.product_code),
                               func.coalesce(Product.name, PriceEntry.name))
                      .outerjoin(Product, Product.id == Payment.product_id)
                      .outerjoin(PriceEntry, and_(PriceEntry.version_id == Payment.pricing_version_id,
                                                 PriceEntry.code == Payment.price_entry_code))
                      .where(Payment.payment_status.in_(CONFIRMED_PAYMENT_STATUSES))).all()
    rows = [(payment, code) for payment, code, _ in raw_rows]
    category_labels = {code: label for _, code, label in raw_rows if code and label}
    dated = [(p, code) for p, code in rows if p.paid_at and not p.paid_at_is_estimated
             and aware(p.paid_at) <= now and (p.amount is None or p.amount > 0)]
    first_payment = {}
    for p, _ in dated:
        if p.user_id:
            key, at = person(p.user_id), aware(p.paid_at)
            first_payment[key] = min(first_payment.get(key, at), at)
    cash = [(p, code) for p, code in dated if start <= aware(p.paid_at) < end]
    exact = [(p, code) for p, code in cash if p.currency == "RUB"
             and p.amount is not None and not p.amount_is_estimated]
    cohort = {key: entry for key, entry in entries.items() if start <= entry["at"] < end}
    uncertain_first = {person(p.user_id) for p, _ in rows if p.user_id
                       and (not p.paid_at or p.paid_at_is_estimated)}
    eligible = {key: entry for key, entry in cohort.items()
                if key not in uncertain_first
                and (key not in first_payment or first_payment[key] >= entry["at"])}
    def cohort_stats(group):
        early = sum(key in first_payment and first_payment[key] < entry["at"] + timedelta(days=30)
                    for key, entry in group.items())
        late = sum(key in first_payment and first_payment[key] >= entry["at"] + timedelta(days=30)
                   for key, entry in group.items())
        n = len(group)
        return {"leads": n, "early_buyers": early, "late_buyers": late,
                "early_rate": round(early * 100 / n, 2) if n else None,
                "late_rate": round(late * 100 / n, 2) if n else None,
                "total_rate": round((early + late) * 100 / n, 2) if n else None,
                "under_30_days": sum(now < entry["at"] + timedelta(days=30) for entry in group.values())}
    groups = {key: cohort_stats({uid: entry for uid, entry in eligible.items() if entry["source"] == key})
              for key in ("paid", "organic", "unknown")}
    categories = defaultdict(lambda: {"payments": 0, "amount": Decimal(), "buyers": set()})
    for payment, code in exact:
        category = "COACHING" if is_coaching_payment(payment, code) else code or "UNASSIGNED"
        categories[category]["payments"] += 1
        categories[category]["amount"] += payment.amount
        if payment.user_id:
            categories[category]["buyers"].add(person(payment.user_id))
    observed = defaultdict(lambda: Decimal())
    period_amount = defaultdict(lambda: Decimal())
    observed_payments = defaultdict(list)
    for payment, _ in dated:
        if payment.user_id and payment.currency == "RUB" and payment.amount is not None and not payment.amount_is_estimated:
            uid = person(payment.user_id)
            if aware(payment.paid_at) >= observation_start:
                observed[uid] += payment.amount
            if start <= aware(payment.paid_at) < end:
                period_amount[uid] += payment.amount
    for payment, code in dated:
        if payment.user_id and aware(payment.paid_at) >= observation_start:
            observed_payments[person(payment.user_id)].append((payment, code))
    buyer_ids = {person(p.user_id) for p, _ in cash if p.user_id}
    people = []
    for uid in sorted(buyer_ids, key=lambda key: (-period_amount[key], key)):
        people.append({"user_id": uid.removeprefix("user:"), "name": names.get(uid, "Без имени"),
            "period_revenue": float(period_amount[uid]), "observed_ltv": float(observed[uid]),
            "support": coaching_payment_summary(observed_payments[uid])})
    paid_buyers = {kind: sum(entries.get(uid, {}).get("source", "unknown") == kind for uid in buyer_ids)
                   for kind in ("paid", "organic", "unknown")}
    return {"period": {"month": month, "start": start.isoformat(), "end": end.isoformat(),
                        "as_of": now.isoformat(), "observation_start": OBSERVATION_START.isoformat()},
        "receipts": {"revenue": float(sum((p.amount for p, _ in exact), Decimal())),
                     "payment_count": len(cash), "buyers": len(buyer_ids), "buyer_sources": paid_buyers,
                     "unlinked_payments": sum(not p.user_id for p, _ in cash),
                     "uncertain_amounts": len(cash) - len(exact)},
        "cohort": {**cohort_stats(eligible), "observed_entries": len(cohort),
                   "already_buyers": sum(uid in first_payment and first_payment[uid] < entry["at"]
                                         for uid, entry in cohort.items()),
                   "unknown_first_purchase": sum(uid in uncertain_first for uid in cohort), "groups": groups},
        "categories": [{"code": code, "label": category_labels.get(code, code), "payments": item["payments"], "amount": float(item["amount"]),
                        "buyers": len(item["buyers"])} for code, item in sorted(categories.items())],
        "support": coaching_payment_summary(cash), "people": people,
        "expenses": expense_totals(db, start, end),
        "coverage": {"undated_payments": sum(not p.paid_at or p.paid_at_is_estimated for p, _ in rows),
                     "unclassified_payments": sum(code is None and not is_coaching_payment(p, code) for p, code in cash),
                     "notes": ["Приток и конверсии — по наблюдаемым входам; полная история подписок не подтверждена.",
                               "Поздняя конверсия без верхнего срока, по состоянию на дату отчёта.",
                               "Свободная оплата без клиента/назначения входит в поступления, но не в LTV человека или сопровождение.",
                               "Клуб, возвраты и автоматический расход Direct пока не подключены к этому экрану.",
                               "Исключения искусственных подписчиков пока не применяются."]}}


@router.get("/facts")
def facts(month: str | None = None, db: Session = Depends(get_db)):
    return report(db, month)
