from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.app_service import AppAccessError, primary_email, resolve_user_for_resource
from app.auth import require_admin
from app.database import get_db
from app.models import (
    MasterclassEvent, MasterclassNotification, OfferCheckout, OfferStage, QuestionnaireAnswer, QuestionnaireRun,
    Resource, User, UserAccess, UserEmail, UserOffer,
)

router = APIRouter(prefix="/api/masterclass", tags=["masterclass"])

ONBOARDING_QUESTIONS = [
    ("parameters", "Параметры", "Рост, вес, возраст. Как менялся вес за последние 6 месяцев и в каком весе вы хотели бы быть через полгода?"),
    ("main_request", "Главный запрос", "Что сейчас болит и что вы хотите изменить с помощью мастер-класса?"),
    ("work", "Работа и распорядок", "Чем вы занимаетесь, какой график, во сколько встаёте и ложитесь, как проводите выходные?"),
    ("training", "Тренировки", "Есть ли тренировки сейчас, сколько часов в неделю, какие и нравятся ли они вам?"),
    ("medical", "Медицинские ограничения", "Есть ли диагнозы, ограничения в питании или непереносимость продуктов?"),
    ("wellbeing", "Самочувствие", "Оцените кожу, волосы, ногти, ЖКТ, энергию и другие важные особенности здоровья."),
    ("habits", "Вредные привычки", "Алкоголь, курение или другие зависимости — коротко или подробно."),
    ("diet_strengths", "Питание сейчас", "Какие слабые и сильные стороны питания и его организации вы замечаете?"),
    ("food_budget", "Расходы на питание", "Сколько примерно в месяц уходит на питание одного взрослого?"),
    ("outside_food", "Еда вне дома", "Как часто едите вне дома, кто готовит и нравится ли вам готовить?"),
    ("calorie_history", "Опыт подсчёта калорий", "Считали ли калории раньше, как долго, с каким результатом и насколько это было тяжело?"),
    ("diet_history", "Диеты и подходы", "Какие подходы к питанию и похудению пробовали и с какими результатами?"),
    ("courses_history", "Другие программы", "Проходили ли другие курсы или марафоны и что из них вынесли?"),
    ("mentoring", "Опыт наставничества", "Работали ли один на один с тренером, диетологом, нутрициологом или психологом?"),
    ("attribution", "Как вы узнали о Сергее", "Откуда пришли и какой материал или мысль особенно зацепили?"),
]

CLOSING_QUESTIONS = [
    ("diet_changes", "Как менялось питание", "Вы сохраняли привычное питание первую неделю или начали менять его раньше?"),
    ("new_discoveries", "Что стало новым", "Что открыло глаза или оказалось особенно важным?"),
    ("applied", "Что удалось применить", "Какие советы уже закрепились в вашем питании?"),
    ("resistance", "Что не подошло", "Что попробовали, но не пошло или вызвало сопротивление?"),
    ("focus", "Главная зона внимания", "Какая часть питания сейчас отстаёт и требует внимания на разборе?"),
    ("questions", "Вопросы к разбору", "Какие теоретические и практические вопросы вы хотите обсудить?"),
    ("weighing", "Взвешивания", "Убедились ли вы, что заполнили данные взвешиваний?"),
    ("consultation_format", "Формат разбора", "Голосовые сообщения или звонок? Если звонок — укажите удобные дни и время."),
]

PRODUCTS = {
    "recipes": {"name": "Система рецептов", "resource": "ACCESS_RECIPES", "standard": 3900, "description": "Как научиться собирать здоровые тарелки быстро, просто и вкусно — от выбора продуктов до собственных блюд."},
    "calories": {"name": "Мини-курс «Калорийный»", "resource": "ACCESS_CALORIES", "standard": 3900, "description": "Как научиться считать калории так, чтобы вам больше никогда не пришлось считать калории."},
    "training": {"name": "Мини-курс «С дивана до тренировок»", "resource": "ACCESS_STRENGTH", "standard": 3900, "description": "Как встать с дивана и начать получать от тренировок и удовольствие, и результат."},
    "recordings": {"name": "Записи консультаций других участников", "resource": "ACCESS_CONSULTATION_RECORDINGS", "standard": 3900, "description": "Практические записи разборов питания и решений других участников."},
}

STAGE_BY_PLACEMENT = {
    "day-2-offer": "early", "recipes-part-1-gate": "early",
    "recipes-part-2-gate": "second", "closing-review": "review",
    "post-review": "last_week",
}


def aware_utc(value: datetime | None) -> datetime | None:
    if value is None: return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class AnswerIn(BaseModel):
    email: str
    question_code: str = Field(min_length=1, max_length=80)
    answer_text: str = Field(default="", max_length=30000)


class RunActionIn(BaseModel):
    email: str


class EventIn(BaseModel):
    email: str
    event_type: str = Field(min_length=1, max_length=80)
    event_key: str = Field(min_length=1, max_length=160)
    placement: str | None = Field(default=None, max_length=80)


class CheckoutIn(BaseModel):
    email: str
    placement: str
    offer_code: str


class StageUpdateIn(BaseModel):
    duration_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    single: int = Field(ge=0, le=1_000_000)
    consultation: int | None = Field(default=None, ge=0, le=1_000_000)
    bundle: dict[str, int]


def resolve_masterclass_user(db: Session, email: str) -> User:
    try:
        return resolve_user_for_resource(db, email, "ACCESS_MASTERCLASS")
    except AppAccessError as exc:
        raise HTTPException(403, str(exc)) from exc


def questions(kind: str) -> list[tuple[str, str, str]]:
    if kind == "onboarding": return ONBOARDING_QUESTIONS
    if kind == "closing-review": return CLOSING_QUESTIONS
    raise HTTPException(404, "questionnaire not found")


def get_run(db: Session, user_id: uuid.UUID, kind: str) -> QuestionnaireRun:
    run = db.scalar(select(QuestionnaireRun).where(QuestionnaireRun.user_id == user_id, QuestionnaireRun.kind == kind))
    if not run:
        run = QuestionnaireRun(user_id=user_id, kind=kind)
        db.add(run); db.flush()
    return run


def queue_notification(db: Session, user_id: uuid.UUID, event: MasterclassEvent, kind: str, due_at: datetime, content_code: str | None = None, payload: dict | None = None) -> None:
    key = f"{event.event_key}:{kind}"
    if not db.scalar(select(MasterclassNotification.id).where(MasterclassNotification.user_id == user_id, MasterclassNotification.deduplication_key == key)):
        db.add(MasterclassNotification(user_id=user_id, event_id=event.id, notification_kind=kind, content_code=content_code, deduplication_key=key, due_at=due_at, payload=payload or {}))


@router.get("/questionnaires/{kind}")
def questionnaire(kind: str, email: str, db: Session = Depends(get_db)) -> dict:
    user = resolve_masterclass_user(db, email)
    run = get_run(db, user.id, kind)
    if kind == "closing-review":
        event = db.scalar(select(MasterclassEvent).where(MasterclassEvent.user_id == user.id, MasterclassEvent.event_key == "closing_review_opened"))
        if not event:
            event = MasterclassEvent(user_id=user.id, event_key="closing_review_opened", event_type="closing_review_opened", placement="closing-review", details={})
            db.add(event); db.flush()
            queue_notification(db, user.id, event, "review_followup", datetime.now(timezone.utc), payload={})
    answers = {row.question_code: row.answer_text for row in db.scalars(select(QuestionnaireAnswer).where(QuestionnaireAnswer.run_id == run.id))}
    db.commit()
    return {"ok": True, "kind": kind, "status": run.status, "questions": [{"code": c, "title": t, "prompt": p, "answer": answers.get(c, "")} for c,t,p in questions(kind)]}


@router.put("/questionnaires/{kind}/answer")
def save_answer(kind: str, body: AnswerIn, db: Session = Depends(get_db)) -> dict:
    user = resolve_masterclass_user(db, body.email)
    valid = {row[0] for row in questions(kind)}
    if body.question_code not in valid: raise HTTPException(422, "unknown question")
    run = get_run(db, user.id, kind)
    answer = db.scalar(select(QuestionnaireAnswer).where(QuestionnaireAnswer.run_id == run.id, QuestionnaireAnswer.question_code == body.question_code))
    if not answer:
        answer = QuestionnaireAnswer(run_id=run.id, question_code=body.question_code)
        db.add(answer)
    answer.answer_text = body.answer_text
    answer.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "saved": body.question_code}


@router.post("/questionnaires/{kind}/{action}")
def finish_questionnaire(kind: str, action: str, body: RunActionIn, db: Session = Depends(get_db)) -> dict:
    if action not in {"submit", "skip"}: raise HTTPException(404, "action not found")
    user = resolve_masterclass_user(db, body.email)
    run = get_run(db, user.id, kind)
    run.status = "submitted" if action == "submit" else "skipped"
    run.submitted_at = datetime.now(timezone.utc)
    event_type = "onboarding_questionnaire_completed" if kind == "onboarding" else "closing_review_submitted"
    event_key = f"{event_type}:v{run.version}"
    event = db.scalar(select(MasterclassEvent).where(MasterclassEvent.user_id == user.id, MasterclassEvent.event_key == event_key))
    if not event:
        event = MasterclassEvent(user_id=user.id, event_key=event_key, event_type=event_type, details={"run_id": str(run.id), "status": run.status})
        db.add(event); db.flush()
    if kind == "closing-review" and action == "submit":
        queue_notification(db, user.id, event, "owner_closing_review", datetime.now(timezone.utc), payload={"run_id": str(run.id)})
    db.commit()
    return {"ok": True, "status": run.status, "messenger_link_status": "planned"}


@router.post("/events")
def record_event(body: EventIn, db: Session = Depends(get_db)) -> dict:
    user = resolve_masterclass_user(db, body.email)
    event = db.scalar(select(MasterclassEvent).where(MasterclassEvent.user_id == user.id, MasterclassEvent.event_key == body.event_key))
    created = event is None
    if created:
        event = MasterclassEvent(user_id=user.id, event_key=body.event_key, event_type=body.event_type, placement=body.placement, details={})
        db.add(event); db.flush()
        if body.event_type == "dqs_opened":
            queue_notification(db, user.id, event, "dqs_support", datetime.now(timezone.utc) + timedelta(hours=6), "tpl_postpurchase_dqs_support")
    db.commit()
    return {"ok": True, "created": created, "event_id": str(event.id)}


def access_codes(db: Session, user_id: uuid.UUID) -> set[str]:
    now = datetime.now(timezone.utc)
    return set(db.scalars(select(Resource.code).join(UserAccess, UserAccess.resource_id == Resource.id).where(UserAccess.user_id == user_id, UserAccess.revoked_at.is_(None), (UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now)))).all())


def offer_stage(db: Session, user: User, placement: str) -> tuple[OfferStage, UserOffer | None]:
    now = datetime.now(timezone.utc)
    order = ["early", "second", "review", "last_week", "standard"]
    if placement == "offers-hub":
        history = list(db.scalars(
            select(UserOffer)
            .where(UserOffer.user_id == user.id)
            .order_by(UserOffer.started_at.desc())
        ))
        own = next(
            (item for item in history if item.expires_at is None or aware_utc(item.expires_at) > now),
            None,
        )

        # The final one-week window follows the review offer automatically.  Its
        # clock starts at the actual review expiry, not when an old page happens
        # to be opened again.  This prevents both skipping and silently extending
        # the agreed final discount.
        if own is None:
            review = next((item for item in history if item.stage_code == "review"), None)
            last_week = next((item for item in history if item.stage_code == "last_week"), None)
            review_expires = aware_utc(review.expires_at) if review else None
            if review_expires and review_expires <= now and last_week is None:
                final_stage = db.scalar(select(OfferStage).where(
                    OfferStage.code == "last_week", OfferStage.status == "active"
                ))
                if not final_stage:
                    raise HTTPException(503, "last-week offer stage is not configured")
                final_expires = (
                    review_expires + timedelta(hours=final_stage.duration_hours)
                    if final_stage.duration_hours else None
                )
                if final_expires is None or final_expires > now:
                    own = UserOffer(
                        user_id=user.id,
                        stage_code="last_week",
                        started_at=review_expires,
                        expires_at=final_expires,
                        snapshot={"created_by": "review_expiry"},
                    )
                    db.add(own)
                    db.flush()

        code = own.stage_code if own else "standard"
        stage = db.scalar(select(OfferStage).where(OfferStage.code == code, OfferStage.status == "active"))
        if not stage: raise HTTPException(503, "offer stage is not configured")
        return stage, own
    code = STAGE_BY_PLACEMENT.get(placement, "standard")
    stage = db.scalar(select(OfferStage).where(OfferStage.code == code, OfferStage.status == "active"))
    if not stage: raise HTTPException(503, "offer stage is not configured")
    own = db.scalar(select(UserOffer).where(UserOffer.user_id == user.id, UserOffer.stage_code == code))
    if own and own.expires_at and aware_utc(own.expires_at) <= now:
        next_code = order[min(order.index(code) + 1, len(order) - 1)]
        next_stage = db.scalar(select(OfferStage).where(OfferStage.code == next_code, OfferStage.status == "active"))
        if not next_stage: raise HTTPException(503, "next offer stage is not configured")
        return next_stage, None
    if not own:
        if code == "standard": return stage, None
        own = UserOffer(user_id=user.id, stage_code=code, started_at=now, expires_at=now + timedelta(hours=stage.duration_hours) if stage.duration_hours else None, snapshot={})
        db.add(own); db.flush()
    return stage, own


def safe_order(name: str, price: int) -> str:
    clean = re.sub(r"[\r\n=:]+", " ", name).strip()
    return f"#order:{clean}={price}"


def build_offers(db: Session, user: User, placement: str) -> dict:
    stage, own = offer_stage(db, user, placement)
    owned = access_codes(db, user.id)
    missing = [(code, p) for code,p in PRODUCTS.items() if p["resource"] not in owned]
    if "ACCESS_CONSULTATION" in owned:
        missing = [(code,p) for code,p in missing if code != "recordings"]
    pricing = stage.pricing or {}
    single_price = int(pricing.get("single", 3900))
    bundle_table = pricing.get("bundle", {})
    cards = []
    if missing:
        code, product = missing[0]
        price = min(single_price, int(product["standard"]))
        cards.append({"code": f"single:{code}", "title": product["name"], "description": product["description"], "details": [{"name": product["name"], "description": product["description"]}], "items": [code], "standard_price": product["standard"], "price": price})
        if len(missing) > 1:
            count = len(missing)
            standard = sum(int(p["standard"]) for _,p in missing)
            price = int(bundle_table.get(str(count), standard))
            title = "Вообще всё, что вам может понадобиться"
            cards.append({"code": "bundle:digital", "title": title, "description": "Все недостающие самостоятельные материалы одним комплектом.", "details": [{"name": p["name"], "description": p["description"]} for _, p in missing], "items": [c for c,_ in missing], "standard_price": standard, "price": price})
    consultation_placements = {"closing-review", "post-review", "offers-hub"}
    if placement in consultation_placements and stage.code in {"review", "last_week", "standard"} and "ACCESS_CONSULTATION" not in owned:
        consult_price = int(pricing.get("consultation", 8900))
        consultation_detail = {"name": "Индивидуальная консультация", "description": "Сначала Сергей разбирает дневник питания, затем вы обсуждаете выводы звонком или голосовыми сообщениями."}
        cards.insert(0, {"code": "single:consultation", "title": "Индивидуальная консультация", "description": "Сначала разбор дневника, затем обсуждение выводов звонком или голосовыми.", "details": [consultation_detail], "items": ["consultation"], "standard_price": 8900, "price": consult_price})
        if missing:
            digital_standard = sum(int(product["standard"]) for _, product in missing)
            digital_price = int(bundle_table.get(str(len(missing)), digital_standard))
            cards.insert(1, {
                "code": "bundle:consultation",
                "title": "Максимальный комплект с консультацией",
                "description": "Индивидуальная консультация и все недостающие самостоятельные материалы одним комплектом.",
                "details": [consultation_detail, *[{"name": p["name"], "description": p["description"]} for _, p in missing]],
                "items": ["consultation", *[code for code, _ in missing]],
                "standard_price": 8900 + digital_standard,
                "price": consult_price + digital_price,
            })
    for card in cards:
        card["saving"] = card["standard_price"] - card["price"]
        card["saving_percent"] = round(card["saving"] * 100 / card["standard_price"]) if card["standard_price"] else 0
    return {"ok": True, "stage": stage.code, "stage_name": stage.name, "expires_at": own.expires_at.isoformat() if own and own.expires_at else None, "owned_resources": sorted(owned), "offers": cards[:3]}


@router.get("/offers")
def offers(email: str, placement: str, db: Session = Depends(get_db)) -> dict:
    user = resolve_masterclass_user(db, email)
    payload = build_offers(db, user, placement)
    db.commit(); return payload


@router.post("/checkout")
def checkout(body: CheckoutIn, db: Session = Depends(get_db)) -> dict:
    user = resolve_masterclass_user(db, body.email)
    payload = build_offers(db, user, body.placement)
    card = next((item for item in payload["offers"] if item["code"] == body.offer_code), None)
    if not card: raise HTTPException(409, "offer is no longer available")
    now = datetime.now(timezone.utc)
    stage_expires = aware_utc(datetime.fromisoformat(payload["expires_at"])) if payload["expires_at"] else None
    checkout_expires = min(stage_expires, now + timedelta(hours=2)) if stage_expires else now + timedelta(hours=2)
    checkout = OfferCheckout(
        user_id=user.id,
        offer_code=card["code"],
        title=card["title"],
        items=card["items"],
        amount=Decimal(card["price"]),
        expires_at=checkout_expires,
    )
    db.add(checkout); db.flush()
    command = safe_order(f"EB-{checkout.id.hex} {card['title']}", card["price"])
    db.commit(); return {"ok": True, "cart_command": command, "expires_at": checkout_expires.isoformat()}


@router.get("/gate/{part}")
def recipe_gate(part: int, email: str, db: Session = Depends(get_db)) -> dict:
    if part not in {1,2}: raise HTTPException(404, "recipe part not found")
    user = resolve_masterclass_user(db, email)
    placement = f"recipes-part-{part}-gate"
    key = f"recipes_part_{part}_opened"
    event = db.scalar(select(MasterclassEvent).where(MasterclassEvent.user_id == user.id, MasterclassEvent.event_key == key))
    if not event:
        event = MasterclassEvent(user_id=user.id, event_key=key, event_type=key, placement=placement, details={})
        db.add(event); db.flush()
        if part == 1:
            queue_notification(db, user.id, event, "recipes_followup", datetime.now(timezone.utc) + timedelta(minutes=60), payload={"part": 1})
        else:
            queue_notification(db, user.id, event, "recipes_second", datetime.now(timezone.utc), "tpl_postpurchase_recipes_second", payload={"part": 2})
    allowed = "ACCESS_RECIPES" in access_codes(db, user.id)
    payload = {"ok": True, "part": part, "allowed": allowed}
    if allowed:
        payload.update({"state": "technical_error", "message": "Доступ подтверждён, но материал не удалось открыть из-за технической ошибки.", "contact": "@FitnessSergey"})
    else:
        payload.update({"state": "offer", "message": "Этот раздел не входит в ваш текущий тариф.", "offer": build_offers(db, user, placement)})
    db.commit(); return payload


@router.get("/admin/offer-stages")
def admin_offer_stages(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    rows = list(db.scalars(select(OfferStage).order_by(OfferStage.created_at)))
    return {"ok": True, "stages": [{"code": row.code, "name": row.name, "duration_hours": row.duration_hours, "pricing": row.pricing, "status": row.status} for row in rows]}


@router.get("/admin/users")
def admin_masterclass_users(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(User.id, User.display_name, UserEmail.email_normalized)
        .join(UserEmail, UserEmail.user_id == User.id)
        .join(UserAccess, UserAccess.user_id == User.id)
        .join(Resource, Resource.id == UserAccess.resource_id)
        .where(
            User.status == "active",
            User.merged_into_user_id.is_(None),
            UserEmail.is_primary.is_(True),
            Resource.code == "ACCESS_MASTERCLASS",
            UserAccess.revoked_at.is_(None),
            (UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now)),
        )
        .distinct()
        .order_by(User.display_name, UserEmail.email_normalized)
        .limit(500)
    ).all()
    return {
        "ok": True,
        "users": [
            {"id": str(user_id), "display_name": display_name or "", "email": email}
            for user_id, display_name, email in rows
        ],
    }


@router.put("/admin/offer-stages/{stage_code}")
def admin_update_offer_stage(stage_code: str, body: StageUpdateIn, _: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    stage = db.scalar(select(OfferStage).where(OfferStage.code == stage_code))
    if not stage: raise HTTPException(404, "offer stage not found")
    allowed_counts = {"1", "2", "3", "4"}
    if set(body.bundle) - allowed_counts or any(value < 0 or value > 1_000_000 for value in body.bundle.values()):
        raise HTTPException(422, "bundle prices must use counts 1..4")
    stage.duration_hours = body.duration_hours
    stage.pricing = {"single": body.single, "consultation": body.consultation, "bundle": body.bundle}
    db.commit()
    return {"ok": True, "code": stage.code}


@router.get("/admin/summary")
def admin_masterclass_summary(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return {"ok": True, "events": db.scalar(select(func.count(MasterclassEvent.id))) or 0, "questionnaires": db.scalar(select(func.count(QuestionnaireRun.id))) or 0, "active_offers": db.scalar(select(func.count(UserOffer.id)).where(UserOffer.status == "active")) or 0, "pending_notifications": db.scalar(select(func.count(MasterclassNotification.id)).where(MasterclassNotification.status == "pending")) or 0}


@router.get("/admin/notifications")
def admin_masterclass_notifications(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    rows = list(db.scalars(select(MasterclassNotification).order_by(MasterclassNotification.created_at.desc()).limit(100)))
    return {
        "ok": True,
        "notifications": [
            {
                "id": str(row.id),
                "email": primary_email(db, row.user_id),
                "kind": row.notification_kind,
                "status": row.status,
                "due_at": aware_utc(row.due_at).isoformat(),
                "sent_at": aware_utc(row.sent_at).isoformat() if row.sent_at else None,
                "error": row.error_message,
            }
            for row in rows
        ],
    }
