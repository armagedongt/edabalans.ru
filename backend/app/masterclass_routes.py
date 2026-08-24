from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import secrets
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.app_service import AppAccessError, primary_email, resolve_user_for_resource
from app.app_auth import create_placement_token, require_app_user, require_placement
from app.auth import require_admin
from app.config import Settings, get_settings
from app.database import get_db
from app.models import (
    MasterclassDayProgress, MasterclassEvent, MasterclassNotification, MasterclassTestProfile,
    MasterclassStepProgress, MessengerAccount, MessengerLinkToken, OfferCheckout, OfferStage,
    QuestionnaireAnswer, QuestionnaireRun, Resource, User, UserAccess, UserEmail, UserOffer,
    UserCoursePolicy,
)
from app.pricing_service import active_pricing_version, pricing_entry_map
from app.product_identity import purchased_products

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
    "recipes": {"name": "Система рецептов", "resource": "ACCESS_RECIPES", "standard": 3900, "description": "Как научиться собирать здоровые тарелки быстро, просто и вкусно — от выбора продуктов до собственных блюд.", "features": [
        {"name": "Рецепты и конструктор блюд", "description": "Готовые сочетания и понятный способ собирать собственные блюда."},
        {"name": "Выбор продуктов и готовой еды", "description": "Ориентиры для магазина, доставки и еды вне дома."},
        {"name": "Вкус и организация готовки", "description": "Как сделать полезную еду удобной и действительно приятной."},
    ]},
    "calories": {"name": "Мини-курс «Калорийный»", "resource": "ACCESS_CALORIES", "standard": 3900, "description": "Как научиться считать калории так, чтобы вам больше никогда не пришлось считать калории.", "features": [
        {"name": "Энергетический баланс без лишней математики", "description": "Понятная связь между питанием, расходом энергии и изменением веса."},
        {"name": "Порции, калории и БЖУ", "description": "Практические примеры без попытки превратить питание в бухгалтерию."},
        {"name": "Подсчёт как временный инструмент", "description": "Как получить навык и постепенно отказаться от постоянных расчётов."},
    ]},
    "training": {"name": "Мини-курс «С дивана до тренировок»", "resource": "ACCESS_STRENGTH", "standard": 3900, "description": "Как встать с дивана и начать получать от тренировок и удовольствие, и результат.", "features": [
        {"name": "Выбор цели и подходящего уровня", "description": "Стартовая точка с учётом опыта, самочувствия и возможностей."},
        {"name": "Минимальный рабочий объём", "description": "Сколько нагрузки действительно нужно для первых результатов."},
        {"name": "Начало без перегруза", "description": "Как встроить тренировки в жизнь и не бросить после первой недели."},
    ]},
    "recordings": {"name": "Записи консультаций других участников", "resource": "ACCESS_CONSULTATION_RECORDINGS", "standard": 3900, "description": "Практические записи разборов питания и решений других участников.", "features": [
        {"name": "Реальные ситуации участников", "description": "Примеры, в которых легко узнать собственные сложности."},
        {"name": "Разбор причин", "description": "Не только отдельные ошибки, но и логика, которая за ними стоит."},
        {"name": "Решения для своей ситуации", "description": "Подходы, которые можно перенести в собственное питание."},
    ]},
}

STAGE_BY_PLACEMENT = {
    "day-1-offer": "early", "day-2-offer": "early", "recipes-part-1-gate": "early",
    "recipes-part-2-gate": "second", "closing-review": "review",
    "post-review": "last_week",
    # Current 21-day web program. Legacy placement names above stay valid for
    # already published Tilda embeds and old signed links.
    "day-15-offer": "early", "day-17-offer": "second",
    "day-19-offer": "review", "day-21-offer": "last_week",
}
EMBED_PLACEMENTS = tuple(STAGE_BY_PLACEMENT) + ("offers-hub",)
COURSE_APP_EVENTS = {
    "dqs": "dqs_opened",
    "recipes-part-1": "recipes_part_1_opened",
    "recipes-part-2": "recipes_part_2_opened",
    "closing-review": "closing_review_opened",
}
COURSE_ACTIVITY_EVENTS = {
    "masterclass_day_opened",
    "masterclass_article_completed",
    "task_opened",
    "task_acknowledged",
    "masterclass_day_completed",
    "dqs_opened",
    "recipes_part_1_opened",
    "recipes_part_2_opened",
    "closing_review_opened",
}
COURSE_CONTENT_ROOT = Path(__file__).resolve().parents[2] / "content" / "masterclass"
COURSE_MANIFEST_PATH = COURSE_CONTENT_ROOT / "course" / "course.json"
DEFAULT_COURSE_TIMEZONE = "Europe/Moscow"
NEXT_DAY_LOCAL_HOUR = 6


def load_course_manifest() -> dict:
    manifest = json.loads(COURSE_MANIFEST_PATH.read_text(encoding="utf-8"))
    days = manifest.get("days")
    if not isinstance(days, list) or not days:
        raise RuntimeError("masterclass course manifest has no days")
    numbers = [item.get("number") for item in days]
    if numbers != list(range(1, len(days) + 1)):
        raise RuntimeError("masterclass course days must be sequential from 1")
    step_ids: set[str] = set()
    for day in days:
        if not isinstance(day.get("checks"), list) or not day["checks"]:
            raise RuntimeError(f"masterclass day {day['number']} has no checks")
        seen_non_article = False
        for step in day.get("steps", []):
            step_id = step.get("id")
            if not step_id or step_id in step_ids:
                raise RuntimeError(f"invalid or duplicate masterclass step id: {step_id}")
            step_ids.add(step_id)
            if not step.get("kind"):
                raise RuntimeError(f"masterclass step has no kind: {step_id}")
            if step["kind"] == "article" and seen_non_article:
                raise RuntimeError(
                    f"masterclass articles must precede app steps: {step_id}"
                )
            seen_non_article = seen_non_article or step["kind"] != "article"
    return manifest


COURSE_MANIFEST = load_course_manifest()
COURSE_DAYS = {day["number"]: day for day in COURSE_MANIFEST["days"]}
COURSE_LAST_DAY = max(COURSE_DAYS)
COURSE_CHECK_COUNTS = {day: len(data["checks"]) for day, data in COURSE_DAYS.items()}
COURSE_APPS = {
    day: step["kind"]
    for day, data in COURSE_DAYS.items()
    for step in data.get("steps", [])
    if step["kind"] in COURSE_APP_EVENTS
}
COURSE_OFFERS = {
    day: (step["placement"], step["event"])
    for day, data in COURSE_DAYS.items()
    for step in data.get("steps", [])
    if step["kind"] == "offer"
}


def course_content_files() -> dict[str, Path]:
    result = {
        "extracted-2026-08-23.json": (
            COURSE_CONTENT_ROOT / "imported-draft" / "extracted-2026-08-23.json"
        )
    }
    for day in COURSE_MANIFEST["days"]:
        for step in day.get("steps", []):
            asset = step.get("contentAsset")
            if asset:
                result.setdefault(asset, COURSE_CONTENT_ROOT / "source-current" / asset)
    return result


COURSE_CONTENT_FILES = course_content_files()


def aware_utc(value: datetime | None) -> datetime | None:
    if value is None: return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class AnswerIn(BaseModel):
    email: str
    question_code: str = Field(min_length=1, max_length=80)
    answer_text: str = Field(default="", max_length=30000)


class RunActionIn(BaseModel):
    email: str
    timezone_name: str = Field(default=DEFAULT_COURSE_TIMEZONE, min_length=1, max_length=64)


class CourseCheckIn(BaseModel):
    email: str
    checked: bool


class EventIn(BaseModel):
    email: str
    event_type: str = Field(min_length=1, max_length=80)
    event_key: str = Field(min_length=1, max_length=160)
    placement: str | None = Field(default=None, max_length=80)


class MessengerLinkIn(BaseModel):
    email: str
    platform: str = Field(default="telegram", pattern="^telegram$")


class CheckoutIn(BaseModel):
    email: str
    placement: str
    placement_token: str = Field(min_length=20, max_length=4096)
    offer_code: str


class StageUpdateIn(BaseModel):
    duration_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    single: int = Field(ge=0, le=1_000_000)
    consultation: int | None = Field(default=None, ge=0, le=1_000_000)
    bundle: dict[str, int]


class TestProfileIn(BaseModel):
    email: str
    enabled: bool = True
    day_interval_seconds: int = Field(default=20, ge=1, le=3600)
    notification_delay_seconds: int = Field(default=10, ge=1, le=3600)


def test_profile(db: Session, user_id: uuid.UUID) -> MasterclassTestProfile | None:
    profile = db.get(MasterclassTestProfile, user_id)
    return profile if profile and profile.enabled else None


def course_timezone(value: str | None) -> tuple[str, ZoneInfo]:
    name = (value or DEFAULT_COURSE_TIMEZONE).strip()
    if not name or len(name) > 64:
        name = DEFAULT_COURSE_TIMEZONE
    try:
        return name, ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        return DEFAULT_COURSE_TIMEZONE, ZoneInfo(DEFAULT_COURSE_TIMEZONE)


def next_local_unlock_at(
    progress: MasterclassDayProgress,
    now: datetime,
) -> datetime:
    _, local_timezone = course_timezone(progress.timezone_name)
    opened_date = aware_utc(progress.first_opened_at).astimezone(local_timezone).date()
    reference = aware_utc(progress.completed_at) if progress.completed_at else aware_utc(now)
    reference_date = reference.astimezone(local_timezone).date()
    study_date = max(opened_date, reference_date)
    local_unlock = datetime.combine(
        study_date + timedelta(days=1),
        time(hour=NEXT_DAY_LOCAL_HOUR),
        tzinfo=local_timezone,
    )
    return local_unlock.astimezone(timezone.utc)


def scheduled_unlock_at(
    db: Session,
    user_id: uuid.UUID,
    progress: MasterclassDayProgress,
    now: datetime,
) -> datetime:
    profile = test_profile(db, user_id)
    if profile:
        return aware_utc(progress.first_opened_at) + timedelta(
            seconds=profile.day_interval_seconds
        )
    return next_local_unlock_at(progress, now)


def masterclass_fully_unlocked(db: Session, user_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(UserCoursePolicy.id)
            .join(Resource, Resource.id == UserCoursePolicy.resource_id)
            .where(
                UserCoursePolicy.user_id == user_id,
                Resource.code == "ACCESS_MASTERCLASS",
                UserCoursePolicy.unlock_mode == "fully_unlocked",
            )
        )
    )


def notification_due(db: Session, user_id: uuid.UUID, normal: datetime) -> datetime:
    profile = test_profile(db, user_id)
    return datetime.now(timezone.utc) + timedelta(seconds=profile.notification_delay_seconds) if profile else normal


def review_week_due(db: Session, user_id: uuid.UUID, opened_at: datetime, day: int, ordinal: int) -> datetime:
    """Keep real calendar days while making the owner's isolated test observable."""
    profile = test_profile(db, user_id)
    if profile:
        return datetime.now(timezone.utc) + timedelta(seconds=profile.notification_delay_seconds * ordinal)
    return aware_utc(opened_at) + timedelta(days=day)


def unopened_day_reminder_due(
    db: Session,
    user_id: uuid.UUID,
    progress: MasterclassDayProgress,
    now: datetime,
) -> datetime:
    profile = test_profile(db, user_id)
    if profile:
        return now + timedelta(seconds=profile.notification_delay_seconds)
    unlock_at = scheduled_unlock_at(db, user_id, progress, now)
    _, local_timezone = course_timezone(progress.timezone_name)
    local_day = unlock_at.astimezone(local_timezone).date()
    return datetime.combine(local_day, time(hour=18), tzinfo=local_timezone).astimezone(timezone.utc)


def resolve_masterclass_user(
    request: Request,
    db: Session,
    email: str,
    settings: Settings,
) -> User:
    return require_app_user(request, email, db, "ACCESS_MASTERCLASS", settings)


def course_step_kinds(day: int) -> list[str]:
    if day not in COURSE_DAYS:
        raise HTTPException(404, "masterclass day not found")
    return [step["kind"] for step in COURSE_DAYS[day].get("steps", [])]


def course_event(
    db: Session,
    user_id: uuid.UUID,
    event_key: str,
    event_type: str,
    *,
    placement: str | None = None,
    details: dict | None = None,
) -> MasterclassEvent:
    details = dict(details or {})
    detail_day = details.get("day")
    if detail_day in COURSE_DAYS and "day_title" not in details:
        details["day_title"] = COURSE_DAYS[detail_day]["title"]
    event = db.scalar(
        select(MasterclassEvent).where(
            MasterclassEvent.user_id == user_id,
            MasterclassEvent.event_key == event_key,
        )
    )
    if not event:
        event = MasterclassEvent(
            user_id=user_id,
            event_key=event_key,
            event_type=event_type,
            placement=placement,
            details=details,
        )
        db.add(event)
        db.flush()
        if event_type in COURSE_ACTIVITY_EVENTS:
            db.execute(
                update(MasterclassNotification)
                .where(
                    MasterclassNotification.user_id == user_id,
                    MasterclassNotification.notification_kind == "course_stalled_72h",
                    MasterclassNotification.status == "pending",
                )
                .values(status="skipped", error_message="newer course activity recorded")
            )
            queue_notification(
                db,
                user_id,
                event,
                "course_stalled_72h",
                notification_due(db, user_id, datetime.now(timezone.utc) + timedelta(hours=72)),
                "tpl_postpurchase_tempo_late",
                payload={
                    "day": details.get("day"),
                    "day_title": details.get("day_title"),
                    "step_index": details.get("step_index"),
                },
            )
    return event


def day_progress(
    db: Session, user_id: uuid.UUID, day: int
) -> MasterclassDayProgress | None:
    return db.scalar(
        select(MasterclassDayProgress).where(
            MasterclassDayProgress.user_id == user_id,
            MasterclassDayProgress.day_number == day,
        )
    )


def course_day_unlock_at(
    db: Session, user_id: uuid.UUID, day: int, now: datetime
) -> datetime | None:
    if day == 1:
        return None
    previous = day_progress(db, user_id, day - 1)
    if not previous:
        return None
    return scheduled_unlock_at(db, user_id, previous, now)


def course_day_can_open(
    db: Session, user_id: uuid.UUID, day: int, now: datetime
) -> tuple[bool, str | None, datetime | None]:
    if masterclass_fully_unlocked(db, user_id):
        return True, None, None
    if day == 1:
        return True, None, None
    previous = day_progress(db, user_id, day - 1)
    if not previous:
        return False, "previous_day_not_opened", None
    unlock_at = scheduled_unlock_at(db, user_id, previous, now)
    if not previous.completed_at:
        return False, "previous_day_not_completed", unlock_at
    if now < unlock_at:
        return False, "timer", unlock_at
    return True, None, unlock_at


def open_course_day(
    db: Session,
    user: User,
    day: int,
    now: datetime,
    timezone_name: str = DEFAULT_COURSE_TIMEZONE,
) -> MasterclassDayProgress:
    course_step_kinds(day)
    existing = day_progress(db, user.id, day)
    if existing:
        return existing
    allowed, reason, unlock_at = course_day_can_open(db, user.id, day, now)
    if not allowed:
        detail = {"reason": reason}
        if unlock_at:
            detail["unlock_at"] = unlock_at.isoformat()
        raise HTTPException(409, detail=detail)
    normalized_timezone, _ = course_timezone(timezone_name)
    progress = MasterclassDayProgress(
        user_id=user.id,
        day_number=day,
        first_opened_at=now,
        timezone_name=normalized_timezone,
        checkmarks={},
    )
    db.add(progress)
    db.flush()
    course_event(
        db,
        user.id,
        f"course:day:{day}:opened",
        "masterclass_day_opened",
        details={"day": day},
    )
    return progress


def completed_step_indexes(db: Session, user_id: uuid.UUID, day: int) -> set[int]:
    return set(
        db.scalars(
            select(MasterclassStepProgress.step_index).where(
                MasterclassStepProgress.user_id == user_id,
                MasterclassStepProgress.day_number == day,
            )
        )
    )


def course_payload(
    db: Session, user: User, settings: Settings, now: datetime
) -> dict:
    progress_rows = {
        row.day_number: row
        for row in db.scalars(
            select(MasterclassDayProgress).where(
                MasterclassDayProgress.user_id == user.id
            )
        )
    }
    step_rows: dict[int, set[int]] = {day: set() for day in range(1, COURSE_LAST_DAY + 1)}
    for row in db.scalars(
        select(MasterclassStepProgress).where(
            MasterclassStepProgress.user_id == user.id
        )
    ):
        step_rows[row.day_number].add(row.step_index)

    days = []
    for day in range(1, COURSE_LAST_DAY + 1):
        progress = progress_rows.get(day)
        can_open, reason, unlock_at = course_day_can_open(db, user.id, day, now)
        kinds = course_step_kinds(day)
        completed = step_rows[day]
        task_unlocked = len(completed) == len(kinds)
        placement = COURSE_OFFERS.get(day)
        placement_payload = None
        if progress and placement:
            offer_index = len(kinds) - 1
            if all(index in completed for index in range(offer_index)):
                placement_payload = {
                    "placement": placement[0],
                    "placement_token": create_placement_token(placement[0], settings),
                }
        app_payload = None
        if progress and day in COURSE_APPS:
            app_code = COURSE_APPS[day]
            app_payload = {"code": app_code}
            if app_code == "recipes-part-1":
                app_payload.update(
                    placement="recipes-part-1-gate",
                    placement_token=create_placement_token("recipes-part-1-gate", settings),
                )
            elif app_code == "recipes-part-2":
                app_payload.update(
                    placement="recipes-part-2-gate",
                    placement_token=create_placement_token("recipes-part-2-gate", settings),
                )
        first_opened = aware_utc(progress.first_opened_at) if progress else None
        next_unlock = scheduled_unlock_at(db, user.id, progress, now) if progress else None
        days.append(
            {
                "number": day,
                "opened": progress is not None,
                "can_open": progress is not None or can_open,
                "locked_reason": None if progress or can_open else reason,
                "unlock_at": unlock_at.isoformat() if unlock_at else None,
                "first_opened_at": first_opened.isoformat() if first_opened else None,
                "timezone_name": progress.timezone_name if progress else None,
                "next_day_unlock_at": next_unlock.isoformat() if next_unlock else None,
                "steps_total": len(kinds),
                "completed_steps": sorted(completed),
                "next_step": next(
                    (index for index in range(len(kinds)) if index not in completed), None
                ),
                "task_unlocked": task_unlocked,
                "task_opened": bool(progress and progress.task_opened_at),
                "checkmarks": progress.checkmarks if progress else {},
                "check_count": COURSE_CHECK_COUNTS[day],
                "completed": bool(progress and progress.completed_at),
                "completed_at": (
                    aware_utc(progress.completed_at).isoformat()
                    if progress and progress.completed_at
                    else None
                ),
                "offer": placement_payload,
                "app": app_payload,
            }
        )
    purchases = purchased_products(db, user.id)
    masterclass_purchase = next(
        (item for item in purchases if str(item.get("product_code") or "").startswith("MASTERCLASS_")),
        None,
    )
    return {
        "ok": True,
        "course_version": COURSE_MANIFEST["courseVersion"],
        "server_now": now.isoformat(),
        "unlock_schedule": "next_local_06_after_completion_day",
        "accelerated_test": bool(test_profile(db, user.id)),
        "fully_unlocked": masterclass_fully_unlocked(db, user.id),
        "current_day": max(progress_rows) if progress_rows else 1,
        "masterclass_tariff": masterclass_purchase["tariff"] if masterclass_purchase else None,
        "days": days,
    }


@router.get("/course/manifest")
def course_manifest(
    email: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    resolve_masterclass_user(request, db, email, settings)
    return COURSE_MANIFEST


def course_step_event(day: int, index: int, kind: str) -> tuple[str, str | None]:
    if kind == "article":
        return "masterclass_article_completed", None
    if kind == "questionnaire":
        return "onboarding_questionnaire_completed", None
    if kind == "messenger":
        return "masterclass_messenger_step_opened", None
    if kind in COURSE_APP_EVENTS:
        return COURSE_APP_EVENTS[kind], kind
    if kind == "offer":
        placement, event_type = COURSE_OFFERS[day]
        return event_type, placement
    return "masterclass_step_completed", None


@router.get("/course")
def course_state(
    email: str,
    request: Request,
    timezone_name: str = DEFAULT_COURSE_TIMEZONE,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, email, settings)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(timezone.utc)
    open_course_day(db, user, 1, now, timezone_name)
    course_event(
        db,
        user.id,
        f"course:visit:{uuid.uuid4().hex}",
        "masterclass_day_opened",
        details={"program_days": COURSE_LAST_DAY},
    )
    db.commit()
    return course_payload(db, user, settings, now)


@router.get("/course/content/{asset_name}")
def course_content(
    asset_name: str,
    email: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    resolve_masterclass_user(request, db, email, settings)
    path = COURSE_CONTENT_FILES.get(asset_name)
    if not path or not path.is_file():
        raise HTTPException(404, "masterclass content not found")
    media_type = "application/json" if path.suffix == ".json" else "text/plain"
    response = FileResponse(path, media_type=media_type)
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


@router.post("/course/days/{day}/open")
def course_open_day(
    day: int,
    body: RunActionIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, body.email, settings)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(timezone.utc)
    open_course_day(db, user, day, now, body.timezone_name)
    db.commit()
    return course_payload(db, user, settings, now)


@router.post("/course/days/{day}/steps/{index}/complete")
def course_complete_step(
    day: int,
    index: int,
    body: RunActionIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, body.email, settings)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(timezone.utc)
    progress = day_progress(db, user.id, day)
    if not progress:
        raise HTTPException(409, detail={"reason": "day_not_opened"})
    kinds = course_step_kinds(day)
    if index < 0 or index >= len(kinds):
        raise HTTPException(404, "masterclass step not found")
    completed = completed_step_indexes(db, user.id, day)
    if index in completed:
        return course_payload(db, user, settings, now)
    if any(previous not in completed for previous in range(index)):
        raise HTTPException(409, detail={"reason": "previous_step_not_completed"})
    kind = kinds[index]
    db.add(
        MasterclassStepProgress(
            user_id=user.id,
            day_number=day,
            step_index=index,
            step_kind=kind,
            completed_at=now,
        )
    )
    event_type, placement = course_step_event(day, index, kind)
    course_event(
        db,
        user.id,
        f"course:day:{day}:step:{index}:completed",
        event_type,
        placement=placement,
        details={"day": day, "step_index": index, "step_kind": kind},
    )
    db.commit()
    return course_payload(db, user, settings, now)


@router.post("/course/days/{day}/task/open")
def course_open_task(
    day: int,
    body: RunActionIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, body.email, settings)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(timezone.utc)
    progress = day_progress(db, user.id, day)
    if not progress:
        raise HTTPException(409, detail={"reason": "day_not_opened"})
    if len(completed_step_indexes(db, user.id, day)) != len(course_step_kinds(day)):
        raise HTTPException(409, detail={"reason": "materials_not_completed"})
    if not progress.task_opened_at:
        progress.task_opened_at = now
        course_event(
            db,
            user.id,
            f"course:day:{day}:task:opened",
            "task_opened",
            details={"day": day},
        )
    db.commit()
    return course_payload(db, user, settings, now)


@router.put("/course/days/{day}/checks/{index}")
def course_update_check(
    day: int,
    index: int,
    body: CourseCheckIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, body.email, settings)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(timezone.utc)
    progress = day_progress(db, user.id, day)
    if not progress or not progress.task_opened_at:
        raise HTTPException(409, detail={"reason": "task_not_opened"})
    if index < 0 or index >= COURSE_CHECK_COUNTS.get(day, 0):
        raise HTTPException(404, "masterclass check not found")
    if progress.completed_at and not body.checked:
        raise HTTPException(409, detail={"reason": "day_already_completed"})
    checkmarks = dict(progress.checkmarks or {})
    checkmarks[str(index)] = body.checked
    progress.checkmarks = checkmarks
    all_checked = all(
        checkmarks.get(str(item)) is True for item in range(COURSE_CHECK_COUNTS[day])
    )
    if all_checked and not progress.completed_at:
        progress.completed_at = now
        course_event(
            db,
            user.id,
            f"course:day:{day}:task:acknowledged",
            "task_acknowledged",
            details={"day": day},
        )
        completed_event = course_event(
            db,
            user.id,
            f"course:day:{day}:completed",
            "masterclass_day_completed",
            details={"day": day},
        )
        if day < COURSE_LAST_DAY:
            unlock_at = scheduled_unlock_at(db, user.id, progress, now)
            queue_notification(
                db,
                user.id,
                completed_event,
                "course_day_unopened_18h",
                unopened_day_reminder_due(db, user.id, progress, now),
                "tpl_postpurchase_day_unopened",
                payload={
                    "day": day + 1,
                    "day_title": COURSE_DAYS[day + 1]["title"],
                    "unlock_at": unlock_at.isoformat(),
                },
            )
        if day == COURSE_LAST_DAY:
            course_event(
                db,
                user.id,
                "course:completed",
                "masterclass_completed",
                details={"day": day},
            )
    db.commit()
    return course_payload(db, user, settings, now)


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


def queue_offer_last_chance(
    db: Session,
    user: User,
    offer: UserOffer,
    placement: str,
) -> None:
    if not offer.expires_at:
        return
    event = course_event(
        db,
        user.id,
        f"offer:{offer.stage_code}:started",
        "offer_window_started",
        placement=placement,
        details={
            "stage": offer.stage_code,
            "expires_at": aware_utc(offer.expires_at).isoformat(),
        },
    )
    offer.trigger_event_id = event.id
    queue_notification(
        db,
        user.id,
        event,
        "sales_last_chance_due",
        notification_due(db, user.id, aware_utc(offer.expires_at) - timedelta(hours=12)),
        payload={"stage": offer.stage_code, "placement": placement},
    )


@router.get("/questionnaires/{kind}")
def questionnaire(
    kind: str,
    email: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, email, settings)
    run = get_run(db, user.id, kind)
    if kind == "closing-review":
        event = db.scalar(select(MasterclassEvent).where(MasterclassEvent.user_id == user.id, MasterclassEvent.event_key == "closing_review_opened"))
        if not event:
            event = MasterclassEvent(user_id=user.id, event_key="closing_review_opened", event_type="closing_review_opened", placement="closing-review", details={})
            db.add(event); db.flush()
            queue_notification(db, user.id, event, "review_followup", datetime.now(timezone.utc), payload={})
            for ordinal, (day, notification_kind, content_code) in enumerate((
                (2, "post_review_day_2", "tpl_postpurchase_review_week_1"),
                (4, "post_review_day_4", "tpl_postpurchase_review_week_2"),
                (7, "post_review_day_7", "tpl_postpurchase_review_week_3"),
            ), start=1):
                queue_notification(
                    db,
                    user.id,
                    event,
                    notification_kind,
                    review_week_due(db, user.id, event.occurred_at, day, ordinal),
                    content_code=content_code,
                    payload={"anchor": "closing_review_opened", "day": day},
                )
    answers = {row.question_code: row.answer_text for row in db.scalars(select(QuestionnaireAnswer).where(QuestionnaireAnswer.run_id == run.id))}
    db.commit()
    return {"ok": True, "kind": kind, "status": run.status, "questions": [{"code": c, "title": t, "prompt": p, "answer": answers.get(c, "")} for c,t,p in questions(kind)]}


@router.put("/questionnaires/{kind}/answer")
def save_answer(
    kind: str,
    body: AnswerIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, body.email, settings)
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
def finish_questionnaire(
    kind: str,
    action: str,
    body: RunActionIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    if action not in {"submit", "skip"}: raise HTTPException(404, "action not found")
    user = resolve_masterclass_user(request, db, body.email, settings)
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
def record_event(
    body: EventIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, body.email, settings)
    event = db.scalar(select(MasterclassEvent).where(MasterclassEvent.user_id == user.id, MasterclassEvent.event_key == body.event_key))
    created = event is None
    if created:
        event = MasterclassEvent(user_id=user.id, event_key=body.event_key, event_type=body.event_type, placement=body.placement, details={})
        db.add(event); db.flush()
    db.commit()
    return {"ok": True, "created": created, "event_id": str(event.id)}


@router.post("/messenger-links")
def create_messenger_link(
    body: MessengerLinkIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, body.email, settings)
    username = settings.telegram_test_bot_username.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        raise HTTPException(503, "Telegram bot is not configured")

    now = datetime.now(timezone.utc)
    purpose = "link_account"
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    for previous in db.scalars(select(MessengerLinkToken).where(
        MessengerLinkToken.user_id == user.id,
        MessengerLinkToken.platform == body.platform,
        MessengerLinkToken.purpose == purpose,
        MessengerLinkToken.consumed_at.is_(None),
        MessengerLinkToken.expires_at > now,
    )):
        previous.expires_at = now

    # 18 random bytes become 24 base64url characters. Together with the M
    # prefix the Telegram start payload is only 25 characters long.
    payload = "M" + secrets.token_urlsafe(18)
    expires_at = now + timedelta(minutes=15)
    db.add(MessengerLinkToken(
        user_id=user.id,
        platform=body.platform,
        purpose=purpose,
        token_hash=hashlib.sha256(payload.encode("ascii")).hexdigest(),
        expires_at=expires_at,
    ))
    db.commit()
    return {
        "ok": True,
        "platform": body.platform,
        "deep_link": f"https://t.me/{username}?start={payload}",
        "expires_at": expires_at.isoformat(),
        "status": "generated",
        "consumption": "pending",
    }


@router.get("/messenger-links/status")
def messenger_link_status(
    request: Request,
    email: str,
    platform: str = "telegram",
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    if platform not in {"telegram", "max"}:
        raise HTTPException(422, "unsupported messenger platform")
    user = resolve_masterclass_user(request, db, email, settings)
    account = db.scalar(
        select(MessengerAccount)
        .where(
            MessengerAccount.user_id == user.id,
            MessengerAccount.platform == platform,
            MessengerAccount.linked_at.is_not(None),
        )
        .order_by(MessengerAccount.linked_at.desc())
    )
    return {
        "ok": True,
        "platform": platform,
        "linked": account is not None,
    }


def access_codes(db: Session, user_id: uuid.UUID) -> set[str]:
    now = datetime.now(timezone.utc)
    return set(db.scalars(select(Resource.code).join(UserAccess, UserAccess.resource_id == Resource.id).where(UserAccess.user_id == user_id, UserAccess.revoked_at.is_(None), (UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now)))).all())


def offer_stage(db: Session, user: User, placement: str) -> tuple[OfferStage, UserOffer | None]:
    now = datetime.now(timezone.utc)
    order = ["early", "second", "review", "last_week", "standard"]
    history = list(db.scalars(
        select(UserOffer)
        .where(UserOffer.user_id == user.id, UserOffer.stage_code.in_(order[:-1]))
        .order_by(UserOffer.started_at.desc())
    ))

    # The final one-week clock starts only from the day-21 checkpoint. Until that
    # checkpoint the next price can be visible without an invented countdown.
    review = next((item for item in history if item.stage_code == "review"), None)
    review_expires = aware_utc(review.expires_at) if review else None

    # A participant can never move backwards by reopening an old Tilda lecture.
    # An expired stage exposes the next price but does not start its timer. The
    # timer starts only when that stage's real checkpoint is opened.
    highest = max(history, key=lambda item: order.index(item.stage_code), default=None)
    floor_code: str | None = None
    floor_offer: UserOffer | None = None
    if highest is not None:
        highest_expires = aware_utc(highest.expires_at)
        if highest_expires is None or highest_expires > now:
            floor_code = highest.stage_code
            floor_offer = highest
        else:
            floor_code = order[min(order.index(highest.stage_code) + 1, len(order) - 1)]
            # Review is followed by one last discounted week.  If a participant
            # returns after that whole window, go straight to the standard price
            # even when no page was opened during the final week.
            if highest.stage_code == "review":
                final_stage = db.scalar(select(OfferStage).where(
                    OfferStage.code == "last_week", OfferStage.status == "active"
                ))
                if not final_stage:
                    raise HTTPException(503, "last-week offer stage is not configured")
                if (
                    highest_expires is not None
                    and final_stage.duration_hours
                    and highest_expires + timedelta(hours=final_stage.duration_hours) <= now
                ):
                    floor_code = "standard"

    requested_code = None if placement == "offers-hub" else STAGE_BY_PLACEMENT.get(placement, "standard")
    if requested_code is None:
        code = floor_code or "standard"
    elif floor_code is None:
        code = requested_code
    else:
        code = order[max(order.index(requested_code), order.index(floor_code))]

    stage = db.scalar(select(OfferStage).where(
        OfferStage.code == code, OfferStage.status == "active"
    ))
    if not stage:
        raise HTTPException(503, f"offer stage is not configured: {code}")

    own = next((item for item in history if item.stage_code == code), None)
    if own and own.expires_at and aware_utc(own.expires_at) <= now:
        own = None
    should_start = (
        placement != "offers-hub"
        and placement != "day-1-offer"
        and requested_code == code
        and code != "standard"
        and own is None
    )
    if should_start:
        started_at = (
            review_expires
            if code == "last_week" and review_expires and review_expires > now
            else now
        )
        own = UserOffer(
            user_id=user.id,
            stage_code=code,
            started_at=started_at,
            expires_at=(
                started_at + timedelta(hours=stage.duration_hours)
                if stage.duration_hours else None
            ),
            snapshot={"created_by": placement},
        )
        db.add(own)
        db.flush()
        queue_offer_last_chance(db, user, own, placement)
    elif floor_offer is not None and floor_offer.stage_code == code:
        own = floor_offer
    return stage, own


def safe_order(name: str, price: int) -> str:
    clean = re.sub(r"[\r\n=:]+", " ", name).strip()
    return f"#order:{clean}={price}"


def build_offers(
    db: Session, user: User, placement: str, *, use_pricing_catalog: bool = False
) -> dict:
    stage, own = offer_stage(db, user, placement)
    owned = access_codes(db, user.id)
    missing = [(code, p) for code,p in PRODUCTS.items() if p["resource"] not in owned]
    if "ACCESS_CONSULTATION" in owned:
        missing = [(code,p) for code,p in missing if code != "recordings"]
    pricing = stage.pricing or {}
    catalog = {}
    pricing_version = None
    if use_pricing_catalog:
        pricing_version = active_pricing_version(db)
        if pricing_version is None:
            raise HTTPException(503, "active pricing version is not configured")
        catalog = pricing_entry_map(db, pricing_version)

    def catalog_amount(code: str, fallback: int) -> int:
        if not use_pricing_catalog:
            return fallback
        entry = catalog.get(code)
        if entry is None or not entry.enabled:
            raise HTTPException(503, f"pricing entry is not configured: {code}")
        return int(entry.sale_amount)

    def standard_amount(code: str, fallback: int) -> int:
        return catalog_amount(f"product.{code}", fallback) if use_pricing_catalog else fallback

    single_price = catalog_amount(
        f"upsell.{stage.code}.single", int(pricing.get("single", 3900))
    )
    legacy_bundle_table = pricing.get("bundle", {})
    bundle_table = {
        str(count): catalog_amount(
            f"upsell.{stage.code}.bundle.{count}",
            int(legacy_bundle_table.get(str(count), count * 3900)),
        )
        for count in range(1, 5)
    }
    cards: list[dict] = []

    def single_card(code: str, product: dict, *, discounted: bool = True) -> dict:
        standard = standard_amount(code, int(product["standard"]))
        return {
            "code": f"single:{code}",
            "composition": "single",
            "title": product["name"],
            "description": product["description"],
            "long_description": product.get("long_description", ""),
            "details": [],
            "items": [code],
            "standard_price": standard,
            "price": min(single_price, standard) if discounted else standard,
            "price_code": f"upsell.{stage.code}.single",
        }

    def digital_bundle() -> dict | None:
        if len(missing) < 2:
            return None
        standard = sum(standard_amount(code, int(product["standard"])) for code, product in missing)
        return {
            "code": "bundle:digital",
            "composition": "bundle",
            "title": "Вообще всё, что вам может понадобиться",
            "description": "Все недостающие самостоятельные материалы одним комплектом.",
            "details": [{"name": product["name"], "description": product["description"]} for _, product in missing],
            "items": [code for code, _ in missing],
            "standard_price": standard,
            "price": int(bundle_table.get(str(len(missing)), standard)),
            "price_code": f"upsell.{stage.code}.bundle.{len(missing)}",
        }

    consultation_details = [
        {"name": "Предварительный разбор дневника", "description": "Сергей заранее изучит записи и подготовит основные выводы."},
        {"name": "Обсуждение удобным способом", "description": "Звонок или голосовые сообщения — в зависимости от вашей ситуации."},
        {"name": "Ответы на личные вопросы", "description": "Рекомендации с учётом именно вашего питания и образа жизни."},
    ]
    consultation_detail = {"name": "Индивидуальная консультация", "description": "Персональный разбор дневника питания и обсуждение выводов."}
    consultation_missing = "ACCESS_CONSULTATION" not in owned
    consultation_visible = consultation_missing and placement in {
        "closing-review", "post-review", "day-19-offer",
        "day-21-offer", "offers-hub",
    }
    consultation_card = {
        "code": "single:consultation",
        "composition": "single",
        "title": "Индивидуальная консультация",
        "description": "Сначала разбор дневника, затем обсуждение выводов звонком или голосовыми.",
        "long_description": "",
        "details": [],
        "items": ["consultation"],
        "standard_price": standard_amount("consultation", 8900),
        "price": catalog_amount(
            f"upsell.{stage.code}.consultation", int(pricing.get("consultation", 8900))
        ) if stage.code in {"review", "last_week", "standard"} else int(pricing.get("consultation", 8900)),
        "price_code": f"upsell.{stage.code}.consultation",
    }

    if stage.code in {"early", "second"}:
        if missing:
            cards.append(single_card(*missing[0]))
            bundle = digital_bundle()
            if bundle:
                cards.append(bundle)
    elif stage.code == "review":
        if consultation_visible:
            cards.append(consultation_card)
            if missing:
                digital_standard = sum(standard_amount(code, int(product["standard"])) for code, product in missing)
                digital_price = int(bundle_table.get(str(len(missing)), digital_standard))
                cards.append({
                    "code": "bundle:consultation",
                    "composition": "bundle",
                    "title": "Максимальный комплект с консультацией",
                    "description": "Индивидуальная консультация и все недостающие самостоятельные материалы одним комплектом.",
                    "details": [consultation_detail, *[{"name": p["name"], "description": p["description"]} for _, p in missing]],
                    "items": ["consultation", *[code for code, _ in missing]],
                    "standard_price": 8900 + digital_standard,
                    "price": consultation_card["price"] + digital_price,
                    "price_code": f"upsell.{stage.code}.consultation+bundle.{len(missing)}",
                    # This card combines several catalog rows, so there is no
                    # single PriceEntry to resolve again in the webhook.
                    "price_entry_code": None,
                })
        if missing:
            cards.append(single_card(*missing[0]))
    elif stage.code == "last_week":
        if consultation_visible:
            cards.append(consultation_card)
        bundle = digital_bundle()
        if bundle:
            cards.append(bundle)
        cards.extend(single_card(*item) for item in missing[: 3 - len(cards)])
    else:
        if consultation_visible:
            cards.append(consultation_card)
        cards.extend(single_card(*item, discounted=False) for item in missing[: 3 - len(cards)])
    for card in cards:
        card["saving"] = card["standard_price"] - card["price"]
        card["saving_percent"] = round(card["saving"] * 100 / card["standard_price"]) if card["standard_price"] else 0
    visible_expiry = None if placement == "day-1-offer" else (
        aware_utc(own.expires_at).isoformat() if own and own.expires_at else None
    )
    masterclass_purchase = next(
        (
            item
            for item in purchased_products(db, user.id)
            if str(item.get("product_code") or "").startswith("MASTERCLASS_")
        ),
        None,
    )
    owned_products = [{
        "code": "masterclass",
        "name": "Мастер-класс по изменению питания и пищевых привычек",
        "tariff": masterclass_purchase["tariff"] if masterclass_purchase else "",
    }]
    owned_products.extend(
        {"code": code, "name": product["name"]}
        for code, product in PRODUCTS.items()
        if product["resource"] in owned
    )
    if "ACCESS_CONSULTATION" in owned:
        owned_products.append({"code": "consultation", "name": "Индивидуальная консультация"})
    return {"ok": True, "stage": stage.code, "stage_name": stage.name, "expires_at": visible_expiry, "owned_resources": sorted(owned), "owned_products": owned_products, "pricing_version_id": str(pricing_version.id) if pricing_version else None, "offers": cards[:3]}


@router.get("/offers")
def offers(
    email: str,
    placement: str,
    placement_token: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, email, settings)
    if placement not in EMBED_PLACEMENTS:
        raise HTTPException(422, "unknown masterclass placement")
    require_placement(request, placement, placement_token, settings)
    payload = build_offers(
        db, user, placement, use_pricing_catalog=settings.pricing_catalog_enabled
    )
    db.commit(); return payload


@router.post("/checkout")
def checkout(
    body: CheckoutIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, body.email, settings)
    if body.placement not in EMBED_PLACEMENTS:
        raise HTTPException(422, "unknown masterclass placement")
    require_placement(request, body.placement, body.placement_token, settings)
    payload = build_offers(
        db, user, body.placement, use_pricing_catalog=settings.pricing_catalog_enabled
    )
    card = next((item for item in payload["offers"] if item["code"] == body.offer_code), None)
    if not card: raise HTTPException(409, "offer is no longer available")
    now = datetime.now(timezone.utc)
    stage_expires = aware_utc(datetime.fromisoformat(payload["expires_at"])) if payload["expires_at"] else None
    checkout_expires = min(stage_expires, now + timedelta(hours=2)) if stage_expires else now + timedelta(hours=2)
    checkout = OfferCheckout(
        user_id=user.id,
        checkout_kind="member_offer",
        pricing_version_id=uuid.UUID(payload["pricing_version_id"]) if payload.get("pricing_version_id") else None,
        price_entry_code=(
            card.get("price_entry_code", card.get("price_code"))
            if payload.get("pricing_version_id")
            else None
        ),
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
def recipe_gate(
    part: int,
    email: str,
    placement_token: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    if part not in {1,2}: raise HTTPException(404, "recipe part not found")
    user = resolve_masterclass_user(request, db, email, settings)
    placement = f"recipes-part-{part}-gate"
    require_placement(request, placement, placement_token, settings)
    key = f"recipes_part_{part}_opened"
    event = db.scalar(select(MasterclassEvent).where(MasterclassEvent.user_id == user.id, MasterclassEvent.event_key == key))
    if not event:
        event = MasterclassEvent(user_id=user.id, event_key=key, event_type=key, placement=placement, details={})
        db.add(event); db.flush()
    allowed = "ACCESS_RECIPES" in access_codes(db, user.id)
    payload = {"ok": True, "part": part, "allowed": allowed}
    if allowed:
        payload.update({
            "state": "content",
            "title": f"Рецепты · часть {part}",
            "message": "Доступ подтверждён. Подборка открыта и будет дополняться без изменения этой ссылки.",
        })
    else:
        payload.update({"state": "offer", "message": "Этот раздел не входит в ваш текущий тариф.", "offer": build_offers(db, user, placement, use_pricing_catalog=settings.pricing_catalog_enabled)})
    db.commit(); return payload


@router.get("/admin/offer-stages")
def admin_offer_stages(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    rows = list(db.scalars(select(OfferStage).order_by(OfferStage.created_at)))
    return {"ok": True, "stages": [{"code": row.code, "name": row.name, "duration_hours": row.duration_hours, "pricing": row.pricing, "status": row.status} for row in rows]}


@router.get("/admin/embed-tokens")
def admin_embed_tokens(
    _: str = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    return {
        "ok": True,
        "placements": {
            placement: create_placement_token(placement, settings)
            for placement in EMBED_PLACEMENTS
        },
    }


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


@router.put("/admin/test-profile")
def admin_set_test_profile(
    body: TestProfileIn,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        user = resolve_user_for_resource(db, body.email, "ACCESS_MASTERCLASS")
    except AppAccessError as exc:
        raise HTTPException(404, str(exc)) from exc
    profile = db.get(MasterclassTestProfile, user.id)
    if not profile:
        profile = MasterclassTestProfile(user_id=user.id)
        db.add(profile)
    profile.enabled = body.enabled
    profile.day_interval_seconds = body.day_interval_seconds
    profile.notification_delay_seconds = body.notification_delay_seconds
    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "ok": True,
        "user_id": str(user.id),
        "enabled": profile.enabled,
        "day_interval_seconds": profile.day_interval_seconds,
        "notification_delay_seconds": profile.notification_delay_seconds,
    }


@router.post("/admin/test-profile/reset")
def admin_reset_test_profile(
    body: TestProfileIn,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        user = resolve_user_for_resource(db, body.email, "ACCESS_MASTERCLASS")
    except AppAccessError as exc:
        raise HTTPException(404, str(exc)) from exc
    run_ids = list(db.scalars(select(QuestionnaireRun.id).where(QuestionnaireRun.user_id == user.id)))
    if run_ids:
        db.execute(delete(QuestionnaireAnswer).where(QuestionnaireAnswer.run_id.in_(run_ids)))
    for model in (
        QuestionnaireRun,
        MasterclassNotification,
        OfferCheckout,
        UserOffer,
        MasterclassStepProgress,
        MasterclassDayProgress,
        MasterclassEvent,
    ):
        db.execute(delete(model).where(model.user_id == user.id))
    db.commit()
    return {"ok": True, "user_id": str(user.id), "reset": True}


@router.get("/admin/client-progress")
def admin_client_progress(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    users = db.execute(
        select(User.id, User.display_name, UserEmail.email_normalized)
        .join(UserEmail, (UserEmail.user_id == User.id) & UserEmail.is_primary.is_(True))
        .join(UserAccess, UserAccess.user_id == User.id)
        .join(Resource, Resource.id == UserAccess.resource_id)
        .where(
            Resource.code == "ACCESS_MASTERCLASS",
            UserAccess.revoked_at.is_(None),
            (UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now)),
        )
        .distinct()
        .order_by(User.display_name, UserEmail.email_normalized)
    ).all()
    result = []
    for user_id, display_name, email in users:
        questionnaires = {
            row.kind: row.status
            for row in db.scalars(select(QuestionnaireRun).where(QuestionnaireRun.user_id == user_id))
        }
        messenger = db.scalar(
            select(MessengerAccount).where(
                MessengerAccount.user_id == user_id,
                MessengerAccount.platform == "telegram",
            )
        )
        profile = db.get(MasterclassTestProfile, user_id)
        result.append({
            "id": str(user_id),
            "display_name": display_name or "",
            "email": email,
            "current_day": db.scalar(select(func.max(MasterclassDayProgress.day_number)).where(MasterclassDayProgress.user_id == user_id)) or 0,
            "onboarding": questionnaires.get("onboarding", "not_started"),
            "closing_review": questionnaires.get("closing-review", "not_started"),
            "telegram": messenger.username if messenger else None,
            "test_mode": bool(profile and profile.enabled),
        })
    return {"ok": True, "users": result}


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


@router.get("/admin/user-offers")
def admin_masterclass_user_offers(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(UserOffer, User.display_name, UserEmail.email_normalized, OfferStage.name)
        .join(User, User.id == UserOffer.user_id)
        .join(UserEmail, (UserEmail.user_id == User.id) & UserEmail.is_primary.is_(True))
        .join(OfferStage, OfferStage.code == UserOffer.stage_code)
        .order_by(UserOffer.started_at.desc())
        .limit(200)
    ).all()
    return {
        "ok": True,
        "offers": [
            {
                "id": str(offer.id),
                "display_name": display_name or "",
                "email": email,
                "stage_code": offer.stage_code,
                "stage_name": stage_name,
                "started_at": aware_utc(offer.started_at).isoformat(),
                "expires_at": aware_utc(offer.expires_at).isoformat() if offer.expires_at else None,
                "status": (
                    "expired"
                    if offer.status == "active" and offer.expires_at and aware_utc(offer.expires_at) <= now
                    else offer.status
                ),
            }
            for offer, display_name, email, stage_name in rows
        ],
    }


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
