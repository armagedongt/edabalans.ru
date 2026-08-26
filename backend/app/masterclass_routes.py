from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
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
from app.app_auth import create_placement_token, require_placement
from app.auth import require_admin
from app.config import Settings, get_settings
from app.database import get_db
from app.models import (
    MasterclassDayProgress, MasterclassEvent, MasterclassNotification, MasterclassTestProfile,
    MasterclassStepProgress, MessengerAccount, MessengerLinkToken, OfferCheckout, OfferStage,
    QuestionnaireAnswer, QuestionnaireRun, Resource, User, UserAccess, UserEmail, UserOffer,
    UserCoursePolicy,
)
from app.masterclass_offer_catalog import (
    ACTIVE_OFFER_PRESENTATION,
    DIGITAL_OFFER_PRODUCT_CODES,
    MIN_CONSULTATION_PRICE,
    OFFER_CARD_COPY,
    SITE_SHORT_OFFER_PRESENTATION,
    bundle_detail,
    offer_products,
    partial_bundle_copy,
)
from app.masterclass_offer_rules import (
    EMBED_PLACEMENTS,
    OFFER_STAGE_ADMIN_RULES,
    OFFER_STAGE_DURATIONS,
    PASSIVE_OFFER_PLACEMENTS,
    STAGE_BY_PLACEMENT,
    WINDOW_START_EVENTS,
    WINDOW_START_PLACEMENTS,
)
from app.pricing_service import active_pricing_version, pricing_entry_map
from app.product_identity import purchased_products
from app.product_catalog_service import product_public
from app.course_structure_service import (
    CourseContext,
    course_context,
    effective_required_check_ids,
    effective_required_step_ids,
)

router = APIRouter(prefix="/api/masterclass", tags=["masterclass"])

ONBOARDING_QUESTIONS = [
    ("parameters", "Параметры", "Рост, вес, возраст. Расскажите, как менялся ваш вес за последние шесть месяцев. В каком весе вы хотели бы быть через полгода?"),
    ("main_request", "Главный запрос, с которым вы пришли", "Какие у вас основные жалобы и что вы хотите изменить? Это максимально открытый вопрос — расскажите о том, что «болит» конкретно у вас и как вы хотите, чтобы мой Мастер-класс и консультация после него помогли именно вам. Одни приходят сбросить килограммы, другие — стать здоровее за счёт качественного питания, третьи хотят оптимизировать рацион для достижения спортивных целей."),
    ("work", "Работа", "Расскажите, чем вы занимаетесь на работе, хотя бы в категориях сидячая/не сидячая, но любые подробности приветствуются. Какой у вас график, во сколько встаёте и ложитесь, как добираетесь до работы и обратно, как проводите выходные?"),
    ("training", "Тренировки", "Есть ли они в вашей жизни прямо сейчас — за последний месяц? Если да, сколько часов в неделю, силовые это или кардио, какой у вас опыт и какова основная цель тренировок: функциональное долголетие, нарастить мышцы, потратить калории или за компанию? Главное — нравится ли вам процесс или вы занимаетесь из-под палки?"),
    ("medical", "Медицинские ограничения", "Если есть медицинские диагнозы, которые могут влиять на ограничения в питании, расскажите о них. Возможно, есть непереносимость каких-то продуктов."),
    ("wellbeing", "Оцените состояние", "Оцените состояние кожи, волос, ногтей, ЖКТ — есть ли регулярные спазмы, тяжесть и прочее, — общей энергии по ходу дня и добавьте любые другие субъективные комментарии о здоровье."),
    ("habits", "Вредные привычки", "Алкоголь, курение, любые зависимости. Можно ответить коротко или развёрнуто."),
    ("diet_strengths", "Слабые и сильные стороны питания", "Какие слабые и сильные стороны в своём питании и организации питания вы сейчас замечаете?"),
    ("food_budget", "Расходы на питание", "Сколько примерно вы тратите в месяц на еду и продукты питания в расчёте на одного взрослого человека — от покупки хлеба и жвачки до ресторанов и попкорна в кино?"),
    ("outside_food", "Еда вне дома", "Как часто вы покупаете еду вне дома — сколько раз в неделю? Имеются в виду основные приёмы пищи, а не небольшой пирожок или мороженое. Готовите ли вы самостоятельно или за это отвечают другие члены семьи? Любите ли вы готовить?"),
    ("calorie_history", "Опыт подсчёта калорий", "Вы когда-то раньше считали калории? Как долго, какую калорийность держали, насколько похудели и было ли это тяжело? Расскажите о своём опыте."),
    ("diet_history", "Диеты и подходы", "Какие диеты или подходы в питании и похудении вы пробовали раньше и каковы были результаты?"),
    ("courses_history", "Другие программы", "Есть ли опыт прохождения других курсов, программ или марафонов по похудению? Что вы оттуда почерпнули, если опыт был позитивным, и что не понравилось, если он был негативным?"),
    ("mentoring", "Опыт наставничества", "Был ли опыт работы один на один с наставником в сфере здоровья: тренером, нутрициологом, диетологом, психологом или психотерапевтом? Что больше всего понравилось в сотрудничестве?"),
    ("attribution", "Откуда вы обо мне узнали", "Как попали в Telegram-канал? Какой пост, видео или отдельная мысль из открытого канала вас больше всего зацепили и почему вы выбрали мой подход к похудению?"),
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

CURRENT_DIET_QUESTIONS = [
    ("whole_grains", "Цельнозерновые крупы и хлеб", ""),
    ("vegetables", "Овощи", ""),
    ("fruits_berries", "Фрукты и ягоды", ""),
    ("greens", "Зелень", ""),
    ("legumes", "Бобовые", ""),
    ("nuts_seeds", "Орехи и семена", ""),
    ("animal_proteins", "Мясо, птица, рыба, яйца", ""),
    ("dairy", "Молочные продукты", ""),
    ("plant_oils", "Растительные масла", ""),
    ("animal_fats", "Сливочное масло и животные жиры", ""),
    ("sweets", "Сладости и десерты", ""),
    ("snacks_fast_food", "Снеки и фастфуд", ""),
    ("convenience_foods", "Полуфабрикаты", ""),
    ("sugary_drinks", "Сладкие напитки", ""),
    ("alcohol", "Алкоголь", ""),
    ("water_unsweetened", "Вода и несладкие напитки", ""),
]

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
DEFAULT_COURSE_TIMEZONE = "Europe/Moscow"
NEXT_DAY_LOCAL_HOUR = 6


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


class AccountOfferCheckoutIn(BaseModel):
    email: str
    offer_code: str
    focus_product_code: str = Field(min_length=1, max_length=40)


class StageUpdateIn(BaseModel):
    duration_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    single: int = Field(ge=0, le=1_000_000)
    consultation: int | None = Field(default=None, ge=0, le=1_000_000)
    bundle: dict[str, int]


class AdminOfferPreviewIn(BaseModel):
    stage_code: str = Field(pattern="^(early|second|review|last_week|standard)$")
    placement: str = Field(min_length=1, max_length=80)
    owned_product_codes: list[str] = Field(default_factory=list, max_length=5)
    tariff_name: str = Field(default="Базовый", max_length=120)
    remaining_hours: int | None = Field(default=None, ge=0, le=168)


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
    # Tilda Members Area is the only interactive login during the transition.
    # The closed page supplies its current email; PostgreSQL only resolves the
    # matching user and product right without asking for a second login.
    try:
        return resolve_user_for_resource(db, email, "ACCESS_MASTERCLASS")
    except AppAccessError as exc:
        raise HTTPException(403, str(exc)) from exc


def course_step_kinds(context: CourseContext, day: int) -> list[str]:
    if day not in context.days:
        raise HTTPException(404, "masterclass day not found")
    return [
        step["kind"]
        for step in context.days[day].get("steps", [])
        if not step.get("hidden", False)
    ]


def current_required_step_ids(context: CourseContext, day: int) -> list[str]:
    if day not in context.days:
        raise HTTPException(404, "masterclass day not found")
    return [
        step["id"]
        for step in context.days[day].get("steps", [])
        if not step.get("hidden", False) and step.get("required", True)
    ]


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
    context = course_context(db)
    if detail_day in context.days and "day_title" not in details:
        details["day_title"] = context.days[detail_day]["title"]
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
    context: CourseContext,
    day: int,
    now: datetime,
    timezone_name: str = DEFAULT_COURSE_TIMEZONE,
) -> MasterclassDayProgress:
    course_step_kinds(context, day)
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
        structure_revision_no=context.revision.version_no,
        required_step_ids=current_required_step_ids(context, day),
        required_check_ids=[
            item["id"]
            for item in context.checks[day]
            if not item.get("hidden", False) and item.get("required", True)
        ],
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


def required_step_indexes(
    context: CourseContext, progress: MasterclassDayProgress, day: int
) -> list[int]:
    required_ids = set(effective_required_step_ids(context, progress, day))
    return [
        index
        for index, step in enumerate(context.days[day].get("steps", []))
        if step["id"] in required_ids
    ]


def finalize_course_day(
    db: Session,
    user: User,
    progress: MasterclassDayProgress,
    day: int,
    context: CourseContext,
    now: datetime,
) -> None:
    if progress.completed_at:
        return
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
    if day < context.last_day:
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
                "day_title": context.days[day + 1]["title"],
                "unlock_at": unlock_at.isoformat(),
            },
        )
    if day == context.last_day:
        course_event(
            db,
            user.id,
            "course:completed",
            "masterclass_completed",
            details={"day": day},
        )


def reconcile_course_progress(
    db: Session, user: User, context: CourseContext, now: datetime
) -> None:
    for progress in db.scalars(
        select(MasterclassDayProgress).where(
            MasterclassDayProgress.user_id == user.id,
            MasterclassDayProgress.completed_at.is_(None),
            MasterclassDayProgress.task_opened_at.is_not(None),
        )
    ):
        day = progress.day_number
        completed = completed_step_indexes(db, user.id, day)
        if any(
            step_index not in completed
            for step_index in required_step_indexes(context, progress, day)
        ):
            continue
        checkmarks = dict(progress.checkmarks or {})
        if all(
            checkmarks.get(check_id) is True
            for check_id in effective_required_check_ids(context, progress, day)
        ):
            finalize_course_day(db, user, progress, day, context, now)


def course_payload(
    db: Session, user: User, settings: Settings, now: datetime, context: CourseContext | None = None
) -> dict:
    context = context or course_context(db)
    progress_rows = {
        row.day_number: row
        for row in db.scalars(
            select(MasterclassDayProgress).where(
                MasterclassDayProgress.user_id == user.id
            )
        )
    }
    step_rows: dict[int, set[int]] = {
        day: set() for day in range(1, context.last_day + 1)
    }
    for row in db.scalars(
        select(MasterclassStepProgress).where(
            MasterclassStepProgress.user_id == user.id
        )
    ):
        if row.day_number in step_rows:
            step_rows[row.day_number].add(row.step_index)

    days = []
    for day in range(1, context.last_day + 1):
        progress = progress_rows.get(day)
        can_open, reason, unlock_at = course_day_can_open(db, user.id, day, now)
        steps = context.days[day].get("steps", [])
        kinds = course_step_kinds(context, day)
        completed_indexes = step_rows[day]
        required_ids = (
            effective_required_step_ids(context, progress, day)
            if progress else current_required_step_ids(context, day)
        )
        required_set = set(required_ids)
        required_indexes = [
            index for index, step in enumerate(steps) if step["id"] in required_set
        ]
        task_unlocked = all(index in completed_indexes for index in required_indexes)
        placement = context.offers.get(day)
        placement_payload = None
        if progress and placement:
            offer_index = next(
                index
                for index, step in enumerate(steps)
                if step["kind"] == "offer"
            )
            required_before_offer = [
                index for index, step in enumerate(steps[:offer_index])
                if step["id"] in required_set
            ]
            if all(index in completed_indexes for index in required_before_offer):
                placement_payload = {
                    "placement": placement[0],
                    "placement_token": create_placement_token(placement[0], settings),
                }
        app_payload = None
        if progress and day in context.apps:
            app_code = context.apps[day]
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
        next_step = next(
            (
                index for index, step in enumerate(steps)
                if step["id"] in required_set and index not in completed_indexes
            ),
            None,
        )
        checkmarks = {}
        if progress:
            stored_marks = dict(progress.checkmarks or {})
            checkmarks = {
                str(index): stored_marks.get(item["id"]) is True
                for index, item in enumerate(context.checks[day])
            }
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
                "required_steps_total": len(required_ids),
                "completed_steps": sorted(completed_indexes),
                "next_step": next_step,
                "task_unlocked": task_unlocked,
                "task_opened": bool(progress and progress.task_opened_at),
                "checkmarks": checkmarks,
                "check_count": len(context.checks[day]),
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
        "course_version": context.manifest["courseVersion"],
        "structure_version": context.revision.version_no,
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
    return course_context(db).manifest


def course_step_event(
    context: CourseContext, day: int, index: int, step: dict
) -> tuple[str, str | None]:
    kind = step["kind"]
    if kind == "article":
        return "masterclass_article_completed", None
    if kind == "questionnaire":
        if step.get("questionnaireKind") == "current-diet":
            return "current_diet_questionnaire_completed", None
        return "onboarding_questionnaire_completed", None
    if kind == "messenger":
        return "masterclass_messenger_step_opened", None
    if kind in COURSE_APP_EVENTS:
        return COURSE_APP_EVENTS[kind], kind
    if kind == "offer":
        placement, event_type = context.offers[day]
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
    context = course_context(db)
    open_course_day(db, user, context, 1, now, timezone_name)
    course_event(
        db,
        user.id,
        f"course:visit:{uuid.uuid4().hex}",
        "masterclass_day_opened",
        details={"program_days": context.last_day},
    )
    reconcile_course_progress(db, user, context, now)
    db.commit()
    return course_payload(db, user, settings, now, context)


@router.get("/course/content/{asset_name}")
def course_content(
    asset_name: str,
    email: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    resolve_masterclass_user(request, db, email, settings)
    path = course_context(db).content_files.get(asset_name)
    if not path or not path.is_file():
        raise HTTPException(404, "masterclass content not found")
    media_type = "application/json" if path.suffix == ".json" else "text/plain"
    response = FileResponse(path, media_type=media_type)
    response.headers["Cache-Control"] = "private, no-cache"
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
    context = course_context(db)
    open_course_day(db, user, context, day, now, body.timezone_name)
    db.commit()
    return course_payload(db, user, settings, now, context)


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
    context = course_context(db)
    progress = day_progress(db, user.id, day)
    if not progress:
        raise HTTPException(409, detail={"reason": "day_not_opened"})
    steps = context.days.get(day, {}).get("steps", [])
    if index < 0 or index >= len(steps):
        raise HTTPException(404, "masterclass step not found")
    step = steps[index]
    if step.get("hidden", False):
        raise HTTPException(404, "masterclass step not found")
    kind = step["kind"]
    completed = completed_step_indexes(db, user.id, day)
    if index in completed:
        return course_payload(db, user, settings, now, context)
    required_ids = set(effective_required_step_ids(context, progress, day))
    required_before = [
        previous_index
        for previous_index, previous in enumerate(steps[:index])
        if previous["id"] in required_ids
    ]
    if any(previous not in completed for previous in required_before):
        raise HTTPException(409, detail={"reason": "previous_step_not_completed"})
    if kind == "dqs":
        tutorial_completed = db.scalar(
            select(MasterclassEvent.id).where(
                MasterclassEvent.user_id == user.id,
                MasterclassEvent.event_key == "dqs_tutorial_completed",
            )
        )
        if not tutorial_completed:
            return course_payload(db, user, settings, now)
    db.add(
        MasterclassStepProgress(
            user_id=user.id,
            day_number=day,
            step_index=index,
            step_kind=kind,
            completed_at=now,
        )
    )
    event_type, placement = course_step_event(context, day, index, step)
    course_event(
        db,
        user.id,
        f"course:day:{day}:step:{index}:completed",
        event_type,
        placement=placement,
        details={
            "day": day, "step_index": index, "step_id": step["id"], "step_kind": kind
        },
    )
    db.commit()
    return course_payload(db, user, settings, now, context)


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
    context = course_context(db)
    progress = day_progress(db, user.id, day)
    if not progress:
        raise HTTPException(409, detail={"reason": "day_not_opened"})
    completed = completed_step_indexes(db, user.id, day)
    if any(
        step_index not in completed
        for step_index in required_step_indexes(context, progress, day)
    ):
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
    return course_payload(db, user, settings, now, context)


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
    context = course_context(db)
    progress = day_progress(db, user.id, day)
    if not progress or not progress.task_opened_at:
        raise HTTPException(409, detail={"reason": "task_not_opened"})
    checks = context.checks.get(day, [])
    if index < 0 or index >= len(checks):
        raise HTTPException(404, "masterclass check not found")
    if checks[index].get("hidden", False):
        raise HTTPException(404, "masterclass check not found")
    check_id = checks[index]["id"]
    checkmarks = dict(progress.checkmarks or {})
    checkmarks[check_id] = body.checked
    progress.checkmarks = checkmarks
    all_checked = all(
        checkmarks.get(item_id) is True
        for item_id in effective_required_check_ids(context, progress, day)
    )
    if all_checked and not progress.completed_at:
        finalize_course_day(db, user, progress, day, context, now)
    db.commit()
    return course_payload(db, user, settings, now, context)


def questions(kind: str) -> list[tuple[str, str, str]]:
    if kind == "onboarding": return ONBOARDING_QUESTIONS
    if kind == "current-diet": return CURRENT_DIET_QUESTIONS
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
        notification_due(db, user.id, aware_utc(offer.expires_at) - timedelta(hours=24)),
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
    questions(kind)
    user = resolve_masterclass_user(request, db, body.email, settings)
    run = get_run(db, user.id, kind)
    run.status = "submitted" if action == "submit" else "skipped"
    run.submitted_at = datetime.now(timezone.utc)
    event_type = {
        "onboarding": "onboarding_questionnaire_completed",
        "current-diet": "current_diet_questionnaire_completed",
        "closing-review": "closing_review_submitted",
    }[kind]
    event_key = f"{event_type}:v{run.version}"
    event = db.scalar(select(MasterclassEvent).where(MasterclassEvent.user_id == user.id, MasterclassEvent.event_key == event_key))
    if not event:
        event = MasterclassEvent(user_id=user.id, event_key=event_key, event_type=event_type, details={"run_id": str(run.id), "status": run.status})
        db.add(event); db.flush()
    if kind == "closing-review" and action == "submit":
        queue_notification(db, user.id, event, "owner_closing_review", datetime.now(timezone.utc), payload={"run_id": str(run.id)})
    if kind == "current-diet" and action == "submit":
        queue_notification(
            db,
            user.id,
            event,
            "current_diet_questionnaire",
            datetime.now(timezone.utc),
            content_code="tpl_postpurchase_current_diet",
            payload={"questionnaire_kind": kind, "run_id": str(run.id)},
        )
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


def configured_offer_stage(db: Session, code: str) -> OfferStage:
    stage = db.scalar(
        select(OfferStage).where(OfferStage.code == code, OfferStage.status == "active")
    )
    if not stage:
        raise HTTPException(503, f"offer stage is not configured: {code}")
    return stage


def create_offer_window(
    db: Session,
    user: User,
    stage: OfferStage,
    placement: str,
    started_at: datetime,
) -> UserOffer:
    existing = db.scalar(
        select(UserOffer).where(
            UserOffer.user_id == user.id,
            UserOffer.stage_code == stage.code,
        )
    )
    if existing:
        return existing
    offer = UserOffer(
        user_id=user.id,
        stage_code=stage.code,
        started_at=started_at,
        expires_at=(
            started_at + timedelta(hours=OFFER_STAGE_DURATIONS[stage.code])
            if OFFER_STAGE_DURATIONS[stage.code]
            else None
        ),
        snapshot={"created_by": placement},
    )
    db.add(offer)
    db.flush()
    queue_offer_last_chance(db, user, offer, placement)
    return offer


def schedule_last_week_from_review(
    db: Session,
    user: User,
    review: UserOffer,
) -> UserOffer:
    if not review.expires_at:
        raise HTTPException(503, "review offer has no expires_at")
    return create_offer_window(
        db,
        user,
        configured_offer_stage(db, "last_week"),
        "automatic-review-expiry",
        aware_utc(review.expires_at),
    )


def timeline_stage(
    history: list[UserOffer], now: datetime
) -> tuple[str | None, UserOffer | None]:
    order = ["early", "second", "review", "last_week", "standard"]
    started = [item for item in history if aware_utc(item.started_at) <= now]
    active = [
        item
        for item in started
        if item.expires_at is None or aware_utc(item.expires_at) > now
    ]
    if active:
        current = max(active, key=lambda item: order.index(item.stage_code))
        return current.stage_code, current
    if not started:
        return None, None
    highest = max(started, key=lambda item: order.index(item.stage_code))
    return order[min(order.index(highest.stage_code) + 1, len(order) - 1)], None


def offer_stage(db: Session, user: User, placement: str, *, readonly: bool = False) -> tuple[OfferStage, UserOffer | None]:
    now = datetime.now(timezone.utc)
    order = ["early", "second", "review", "last_week", "standard"]
    # Serialize the first opening of a checkpoint. UserOffer has an additional
    # unique constraint, but the user row lock keeps concurrent requests from
    # racing into two window creations.
    if not readonly:
        db.execute(select(User.id).where(User.id == user.id).with_for_update())
    history = list(
        db.scalars(
            select(UserOffer).where(
                UserOffer.user_id == user.id,
                UserOffer.stage_code.in_(order[:-1]),
            )
        )
    )
    review = next((item for item in history if item.stage_code == "review"), None)
    if review and not any(item.stage_code == "last_week" for item in history):
        if readonly:
            history.append(UserOffer(
                user_id=user.id, stage_code="last_week",
                started_at=aware_utc(review.expires_at),
                expires_at=aware_utc(review.expires_at) + timedelta(hours=OFFER_STAGE_DURATIONS["last_week"]),
                snapshot={"created_by": "readonly-preview"},
            ))
        else:
            history.append(schedule_last_week_from_review(db, user, review))
    current_code, current_offer = timeline_stage(history, now)
    requested_code = STAGE_BY_PLACEMENT.get(placement)
    if placement in PASSIVE_OFFER_PLACEMENTS:
        requested_code = None

    # An expired second window does not itself create the review window. Until
    # day 19 starts review, old recipe placements fall back to standard prices.
    review_not_started = current_code == "review" and review is None

    if requested_code and placement in WINDOW_START_PLACEMENTS.get(requested_code, set()):
        if review_not_started and requested_code == "review":
            current_code, current_offer = None, None
        target_code = requested_code if current_code is None else order[
            max(order.index(requested_code), order.index(current_code))
        ]
        existing = next(
            (item for item in history if item.stage_code == requested_code), None
        )
        if target_code == requested_code and existing is None:
            checkpoint = db.scalar(
                select(MasterclassEvent).where(
                    MasterclassEvent.user_id == user.id,
                    MasterclassEvent.event_type == WINDOW_START_EVENTS[requested_code],
                )
            )
            started_at = (
                aware_utc(checkpoint.occurred_at)
                if checkpoint is not None
                else now
            )
            if not readonly:
                created = create_offer_window(
                    db, user, configured_offer_stage(db, requested_code), placement, started_at,
                )
                history.append(created)
                if requested_code == "review":
                    history.append(schedule_last_week_from_review(db, user, created))
                current_code, current_offer = timeline_stage(history, now)

    if review_not_started and not (
        requested_code == "review"
        and placement in WINDOW_START_PLACEMENTS.get("review", set())
    ):
        current_code, current_offer = "standard", None

    code = current_code or (
        "early" if placement in {"day-1-offer", "day-2-offer"} else "standard"
    )
    return configured_offer_stage(db, code), current_offer


def safe_order(name: str, price: int) -> str:
    clean = re.sub(r"[\r\n=:]+", " ", name).strip()
    return f"#order:{clean}={price}"


def offer_checkout_order(checkout: OfferCheckout, price: int) -> str:
    reference = checkout.id.hex[:8].upper()
    return safe_order(f"{checkout.title} · №{reference}", price)


def build_offers(
    db: Session,
    user: User | None,
    placement: str,
    *,
    use_pricing_catalog: bool = False,
    stage_override: str | None = None,
    owned_resources_override: set[str] | None = None,
    tariff_override: str | None = None,
    focus_product_code: str | None = None,
    readonly: bool = False,
) -> dict:
    products = offer_products(db)
    if stage_override is None:
        if user is None:
            raise ValueError("user is required without a preview stage")
        stage, own = offer_stage(db, user, placement, readonly=readonly)
    else:
        stage, own = configured_offer_stage(db, stage_override), None
    owned = (
        set(owned_resources_override)
        if owned_resources_override is not None
        else access_codes(db, user.id)
    )
    presentation = (
        SITE_SHORT_OFFER_PRESENTATION
        if ACTIVE_OFFER_PRESENTATION == SITE_SHORT_OFFER_PRESENTATION["code"]
        else None
    )
    digital_product_codes = (
        presentation["digital_product_codes"]
        if presentation else DIGITAL_OFFER_PRODUCT_CODES
    )
    missing = [
        (code, products[code])
        for code in digital_product_codes
        if products[code]["status"] == "active" and products[code]["resource"] not in owned
    ]
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
        missing_codes = [code for code, _ in missing]
        copy = (
            OFFER_CARD_COPY["digital_bundle"]
            if set(missing_codes) == set(digital_product_codes)
            else partial_bundle_copy(missing_codes, products)
        )
        return {
            "code": "bundle:digital",
            "composition": "bundle",
            "title": copy["title"],
            "description": copy["description"],
            "details": [bundle_detail(code, products) for code, _ in missing],
            "items": [code for code, _ in missing],
            "standard_price": standard,
            "price": int(bundle_table.get(str(len(missing)), standard)),
            "price_code": f"upsell.{stage.code}.bundle.{len(missing)}",
        }

    consultation = products["consultation"]
    consultation_detail = bundle_detail("consultation", products)
    consultation_missing = "ACCESS_CONSULTATION" not in owned
    consultation_visible = consultation_missing and placement in {
        "closing-review", "post-review", "day-19-offer",
        "day-21-offer", "offers-hub",
    }
    consultation_price = catalog_amount(
        f"upsell.{stage.code}.consultation",
        int(pricing.get("consultation", consultation["standard"])),
    ) if stage.code in {"review", "last_week", "standard"} else int(
        pricing.get("consultation", consultation["standard"])
    )
    if consultation_price < MIN_CONSULTATION_PRICE:
        raise HTTPException(503, "consultation price is below the approved minimum")
    consultation_card = {
        "code": "single:consultation",
        "composition": "single",
        "title": consultation["name"],
        "description": consultation["description"],
        "long_description": consultation["long_description"],
        "details": [],
        "items": ["consultation"],
        "standard_price": standard_amount("consultation", consultation["standard"]),
        "price": consultation_price,
        "price_code": f"upsell.{stage.code}.consultation",
    }

    if presentation:
        site_short_prices = pricing.get(presentation["consultation_addon_key"], {})
        consultation_addon = int(site_short_prices.get("consultation_addon", 0))
        if stage.code != "standard" and consultation_missing and consultation_addon < MIN_CONSULTATION_PRICE:
            raise HTTPException(503, "site short consultation price is below the approved minimum")

        def site_short_consultation_card(*, standalone: bool = False) -> dict:
            if standalone or not missing:
                price = (
                    int(pricing.get("consultation", consultation["standard"]))
                    if stage.code in presentation["standalone_consultation_stages"]
                    else consultation_addon
                )
                return {
                    **consultation_card,
                    "price": price,
                    "price_code": f"upsell.site-short.{stage.code}.consultation",
                    "price_entry_code": None,
                }
            digital_standard = sum(
                standard_amount(code, int(product["standard"]))
                for code, product in missing
            )
            digital_price = (
                int(bundle_table[str(len(missing))])
                if len(missing) > 1
                else single_card(*missing[0])["price"]
            )
            details = [*[bundle_detail(code, products) for code, _ in missing], consultation_detail]
            missing_codes = [code for code, _ in missing]
            copy = (
                OFFER_CARD_COPY["consultation_bundle"]
                if set(missing_codes) == set(digital_product_codes)
                else partial_bundle_copy(
                    missing_codes, products, includes_consultation=True,
                )
            )
            return {
                "code": "bundle:site-short-consultation",
                "composition": "bundle",
                "title": copy["title"],
                "description": copy["description"],
                "long_description": "",
                "details": details,
                "items": [*[code for code, _ in missing], "consultation"],
                "standard_price": digital_standard + consultation_card["standard_price"],
                "price": digital_price + consultation_addon,
                "price_code": f"upsell.site-short.{stage.code}.bundle-consultation",
                "price_entry_code": None,
            }

        if stage.code == "early" and placement == "day-1-offer":
            if missing:
                cards.append(single_card(*missing[0]))
                bundle = digital_bundle()
                if bundle:
                    cards.append(bundle)
        elif stage.code in {"early", "second"}:
            if missing:
                cards.append(single_card(*missing[0]))
                bundle = digital_bundle()
                if bundle:
                    cards.append(bundle)
            if consultation_missing and missing:
                cards.append(site_short_consultation_card())
        elif stage.code == "review":
            bundle = digital_bundle()
            if bundle:
                cards.append(bundle)
            elif missing:
                cards.append(single_card(*missing[0]))
            if consultation_missing and missing:
                cards.append(site_short_consultation_card())
            if consultation_missing and placement in {"day-19-offer", "closing-review"}:
                cards.append(site_short_consultation_card(standalone=True))
        elif stage.code == "last_week":
            if missing:
                cards.append(single_card(*missing[0]))
                bundle = digital_bundle()
                if bundle:
                    cards.append(bundle)
            if consultation_missing and missing:
                cards.append(site_short_consultation_card())
        else:
            cards.extend(single_card(*item, discounted=False) for item in missing)
            if consultation_missing and placement in {"day-21-offer", "offers-hub"}:
                cards.append(site_short_consultation_card(standalone=True))
    elif stage.code in {"early", "second"}:
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
                missing_codes = [code for code, _ in missing]
                copy = (
                    OFFER_CARD_COPY["consultation_bundle"]
                    if set(missing_codes) == set(digital_product_codes)
                    else partial_bundle_copy(
                        missing_codes, products, includes_consultation=True,
                    )
                )
                cards.append({
                    "code": "bundle:consultation",
                    "composition": "bundle",
                    "title": copy["title"],
                    "description": copy["description"],
                    "details": [
                        consultation_detail,
                        *[bundle_detail(code, products) for code, _ in missing],
                    ],
                    "items": ["consultation", *[code for code, _ in missing]],
                    "standard_price": consultation_card["standard_price"] + digital_standard,
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
    ) if user is not None and tariff_override is None else None
    owned_products = [{
        "code": "masterclass",
        "name": product_public(db, "masterclass")["name"],
        "tariff": tariff_override or (
            masterclass_purchase["tariff"] if masterclass_purchase else ""
        ),
    }]
    owned_products.extend(
        {"code": code, "name": product["name"]}
        for code in digital_product_codes
        for product in (products[code],)
        if product["resource"] in owned
    )
    if "ACCESS_CONSULTATION" in owned:
        owned_products.append({
            "code": "consultation",
            "name": products["consultation"]["name"],
        })
    focusable_product_codes = [code for code, _ in missing]
    if consultation_missing:
        focusable_product_codes.append("consultation")
    if focus_product_code is not None:
        if focus_product_code not in focusable_product_codes:
            raise HTTPException(409, "Этот продукт сейчас недоступен для покупки")
        if focus_product_code == "consultation":
            focused_single = consultation_card
        else:
            focused_product = next(
                product for code, product in missing if code == focus_product_code
            )
            focused_single = single_card(focus_product_code, focused_product)
        focused_bundles = [
            card for card in cards
            if card["composition"] == "bundle" and focus_product_code in card["items"]
        ]
        cards = [focused_single, *focused_bundles[:2]]
    for card in cards:
        card["saving"] = card["standard_price"] - card["price"]
        card["saving_percent"] = round(card["saving"] * 100 / card["standard_price"]) if card["standard_price"] else 0
    visible_cards = cards[:3]
    visible_product_codes = {
        product_code
        for card in visible_cards
        for product_code in card["items"]
    }
    product_presentations = {
        product_code: {
            "code": product_code,
            "name": products[product_code]["name"],
            "description": products[product_code]["description"],
            "intro": products[product_code]["presentation_intro"],
            "features": products[product_code]["features"],
            "program": products[product_code]["presentation_program"],
        }
        for product_code in visible_product_codes
    }
    product_offer_actions: dict[str, list[dict]] = {code: [] for code in visible_product_codes}
    for card in visible_cards:
        for product_code in card["items"]:
            product_offer_actions[product_code].append({
                "offer_code": card["code"],
                "composition": card["composition"],
                "title": card["title"],
                "price": card["price"],
                "standard_price": card["standard_price"],
                "saving": card["saving"],
                "saving_percent": card["saving_percent"],
                "items": card["items"],
            })
    return {"ok": True, "stage": stage.code, "stage_name": stage.name, "presentation": presentation["code"] if presentation else "canonical", "presentation_name": presentation["name"] if presentation else "Полный канонический каталог", "expires_at": visible_expiry, "owned_resources": sorted(owned), "owned_products": owned_products, "pricing_version_id": str(pricing_version.id) if pricing_version else None, "offers": visible_cards, "focus_product_code": focus_product_code, "focusable_product_codes": focusable_product_codes, "product_presentations": product_presentations, "product_offer_actions": product_offer_actions}


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
        db, user, placement, use_pricing_catalog=settings.pricing_catalog_enabled,
    )
    db.commit(); return payload


@router.get("/account-offers")
def account_offers(
    request: Request,
    email: str,
    focus_product_code: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Read-only offers entry from the Tilda Members Area course dashboard."""
    user = resolve_masterclass_user(request, db, email, settings)
    return build_offers(
        db,
        user,
        "offers-hub",
        use_pricing_catalog=settings.pricing_catalog_enabled,
        focus_product_code=focus_product_code,
        readonly=True,
    )


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
    command, checkout_expires = create_offer_checkout(db, user, payload, card)
    db.commit(); return {"ok": True, "cart_command": command, "expires_at": checkout_expires.isoformat()}


@router.post("/account-offers/checkout")
def account_offer_checkout(
    body: AccountOfferCheckoutIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = resolve_masterclass_user(request, db, body.email, settings)
    payload = build_offers(
        db,
        user,
        "offers-hub",
        use_pricing_catalog=settings.pricing_catalog_enabled,
        focus_product_code=body.focus_product_code,
        readonly=True,
    )
    card = next((item for item in payload["offers"] if item["code"] == body.offer_code), None)
    if not card:
        raise HTTPException(409, "offer is no longer available")
    command, checkout_expires = create_offer_checkout(db, user, payload, card)
    db.commit()
    return {"ok": True, "cart_command": command, "expires_at": checkout_expires.isoformat()}


def create_offer_checkout(
    db: Session, user: User, payload: dict, card: dict
) -> tuple[str, datetime]:
    """Persist one recomputed checkout for an offer card already authorised by build_offers."""
    now = datetime.now(timezone.utc)
    # Serialise pending checkout creation for one member without introducing a
    # second checkout table or a database migration.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    stage_expires = aware_utc(datetime.fromisoformat(payload["expires_at"])) if payload["expires_at"] else None
    checkout_expires = min(stage_expires, now + timedelta(hours=2)) if stage_expires else now + timedelta(hours=2)
    existing = db.scalar(
        select(OfferCheckout)
        .where(
            OfferCheckout.user_id == user.id,
            OfferCheckout.checkout_kind == "member_offer",
            OfferCheckout.offer_code == card["code"],
            OfferCheckout.status == "pending",
            OfferCheckout.expires_at > now,
        )
        .order_by(OfferCheckout.created_at.desc())
    )
    if existing is not None and list(existing.items or []) == list(card["items"]):
        if Decimal(existing.amount) == Decimal(card["price"]):
            return (
                offer_checkout_order(existing, card["price"]),
                aware_utc(existing.expires_at),
            )
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
    db.add(checkout)
    db.flush()
    return offer_checkout_order(checkout, card["price"]), checkout_expires


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
    return {"ok": True, "presentation": ACTIVE_OFFER_PRESENTATION, "stages": [{"code": row.code, "name": row.name, "duration_hours": row.duration_hours, "pricing": row.pricing, "status": row.status, "runtime_rule": OFFER_STAGE_ADMIN_RULES.get(row.code, "")} for row in rows]}


@router.post("/admin/offer-preview")
def admin_offer_preview(
    body: AdminOfferPreviewIn,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    if body.placement not in EMBED_PLACEMENTS:
        raise HTTPException(422, "unknown masterclass placement")
    products = offer_products(db)
    unknown = set(body.owned_product_codes) - set(products)
    if unknown:
        raise HTTPException(422, "unknown preview product")
    owned_resources = {
        products[code]["resource"] for code in body.owned_product_codes
    }
    payload = build_offers(
        db,
        None,
        body.placement,
        use_pricing_catalog=settings.pricing_catalog_enabled,
        stage_override=body.stage_code,
        owned_resources_override=owned_resources,
        tariff_override=body.tariff_name,
    )
    payload["expires_at"] = (
        (datetime.now(timezone.utc) + timedelta(hours=body.remaining_hours)).isoformat()
        if body.remaining_hours is not None
        else None
    )
    return payload


@router.get("/admin/offer-preview/clients")
def admin_offer_preview_clients(
    q: str = "",
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    query = q.strip().lower()
    if len(query) < 3:
        return {"ok": True, "clients": []}
    rows = db.execute(
        select(User.id, User.display_name, UserEmail.email_normalized)
        .join(UserEmail, UserEmail.user_id == User.id)
        .where(UserEmail.email_normalized.ilike(f"%{query}%"))
        .order_by(UserEmail.email_normalized).limit(12)
    ).all()
    return {"ok": True, "clients": [
        {"user_id": str(user_id), "name": name or "", "email": email}
        for user_id, name, email in rows
    ]}


@router.get("/admin/offer-preview/clients/{user_id}")
def admin_offer_preview_client_context(
    user_id: uuid.UUID,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "client not found")
    email = db.scalar(select(UserEmail.email_normalized).where(
        UserEmail.user_id == user.id, UserEmail.is_primary.is_(True)
    )) or db.scalar(select(UserEmail.email_normalized).where(UserEmail.user_id == user.id))
    accesses = sorted(access_codes(db, user.id))
    progress = list(db.scalars(select(MasterclassDayProgress).where(
        MasterclassDayProgress.user_id == user.id
    )))
    current_day = max((row.day_number for row in progress), default=0)
    opened = db.scalar(select(MasterclassEvent).where(
        MasterclassEvent.user_id == user.id,
        MasterclassEvent.placement.in_(EMBED_PLACEMENTS),
    ).order_by(MasterclassEvent.occurred_at.desc()))
    base = {
        "ok": True, "client": {"user_id": str(user.id), "name": user.display_name or "", "email": email},
        "accesses": accesses, "progress": {"current_day": current_day, "opened_days": sorted(row.day_number for row in progress)},
    }
    if "ACCESS_MASTERCLASS" not in accesses:
        return {**base, "state": "no_masterclass_access", "reason": "У человека нет действующего доступа к Мастер-классу.", "offer": None}
    if current_day == 0:
        return {**base, "state": "no_progress", "reason": "Прогресс Мастер-класса ещё не начат, поэтому текущей точки предложения нет.", "offer": None}
    if opened is None:
        return {**base, "state": "no_offer_opened", "reason": "Участник ещё не открывал блок с дополнительным предложением. Просмотр не запускает его вместо участника.", "offer": None}
    offer = build_offers(db, user, opened.placement, use_pricing_catalog=settings.pricing_catalog_enabled, readonly=True)
    return {**base, "state": "offer", "reason": "Показана текущая серверная витрина без изменения данных участника.", "placement": opened.placement, "offer": offer}


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
    canonical_duration = OFFER_STAGE_DURATIONS.get(stage_code)
    if stage_code not in OFFER_STAGE_DURATIONS or body.duration_hours != canonical_duration:
        raise HTTPException(422, "offer duration is fixed by OFFERS_MODULE.md")
    stage.duration_hours = canonical_duration
    stage.pricing = {
        **(stage.pricing or {}),
        "single": body.single,
        "consultation": body.consultation,
        "bundle": body.bundle,
    }
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
