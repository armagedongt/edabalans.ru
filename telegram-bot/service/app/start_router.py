from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import has_paid_product, personalized_delivery, start_run
from app.graph import START_ROUTER_RULES
from app.customer_lifecycle import stop_presale_runs_for_user
from app.content_formatting import content_is_runtime_ready, replace_template_values
from app.models import Contact, ContentItem, ManualMessage, Sequence, SequenceRun, SequenceVersion, StepDelivery, TrackingEvent
from app.seed import WELCOME_CODE
from app.telegram import TelegramError


MASTERCLASS_CODES = ["MASTERCLASS_BASIC", "MASTERCLASS_RECIPES", "MASTERCLASS_CONSULT"]
ACTIVE_RUN_STATUSES = ["active", "waiting"]
DAY_FOUR_STEP_KEY = "welcome_day4"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartFacts:
    is_first_visit: bool
    has_masterclass: bool
    day_four_sent: bool
    has_active_welcome_run: bool
    welcome_ever_started: bool


@dataclass(frozen=True)
class StartDecision:
    code: str
    label: str
    content_code: str | None = None
    starts_welcome: bool = False
    sends_message: bool = False
    manual_review: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


DECISIONS = {
    "masterclass_owned": StartDecision("masterclass_owned", "Мастер-класс куплен: остановить сообщения до покупки и отправить памятку", "tpl_start_masterclass_owned", sends_message=True),
    "launch_welcome": StartDecision("launch_welcome", "Первый вход: кружок, персональный вход в интенсив и расписание", starts_welcome=True, sends_message=True),
    "intensive_complete": StartDecision("intensive_complete", "Интенсив завершён: отправить оглавление", "tpl_intensive_entry_delivered", sends_message=True),
    "intensive_waiting": StartDecision("intensive_waiting", "Интенсив идёт: сообщить время следующего материала", "tpl_intensive_entry_continue", sends_message=True),
    "legacy_update": StartDecision("legacy_update", "Старому участнику показать обновлённый открытый интенсив", "tpl_intensive_entry_legacy_update", sends_message=True),
}


def decision_from_facts(facts: StartFacts) -> StartDecision:
    for fact_name, expected, decision_code in START_ROUTER_RULES:
        if fact_name == "__default__" or bool(getattr(facts, fact_name)) is expected:
            return DECISIONS[decision_code]
    raise RuntimeError("Start router has no terminal rule")


def _welcome_runs(session: Session, contact_id: str):
    return (
        select(SequenceRun)
        .join(SequenceVersion, SequenceVersion.id == SequenceRun.sequence_version_id)
        .join(Sequence, Sequence.id == SequenceVersion.sequence_id)
        .where(SequenceRun.contact_id == contact_id, Sequence.code == WELCOME_CODE)
    )


def active_welcome_run(session: Session, contact_id: str) -> SequenceRun | None:
    return session.scalar(
        _welcome_runs(session, contact_id)
        .where(SequenceRun.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(SequenceRun.started_at.desc())
    )


def inspect_start_facts(session: Session, contact: Contact, is_first_visit: bool) -> StartFacts:
    welcome_run_ids = _welcome_runs(session, contact.id).with_only_columns(SequenceRun.id)
    day_four_sent = bool(session.scalar(
        select(StepDelivery.id)
        .where(
            StepDelivery.run_id.in_(welcome_run_ids),
            StepDelivery.step_key == DAY_FOUR_STEP_KEY,
            StepDelivery.status == "sent",
        )
        .limit(1)
    ))
    run = active_welcome_run(session, contact.id)
    ever_started = bool(session.scalar(_welcome_runs(session, contact.id).with_only_columns(SequenceRun.id).limit(1)))
    return StartFacts(
        is_first_visit=is_first_visit,
        has_masterclass=has_paid_product(session, contact, MASTERCLASS_CODES, "masterclass"),
        day_four_sent=day_four_sent,
        has_active_welcome_run=bool(run),
        welcome_ever_started=ever_started,
    )


def inspect_start(session: Session, contact: Contact, is_first_visit: bool) -> tuple[StartFacts, StartDecision, SequenceRun | None]:
    facts = inspect_start_facts(session, contact, is_first_visit)
    return facts, decision_from_facts(facts), active_welcome_run(session, contact.id)


def _wait_values(run: SequenceRun | None) -> dict[str, str]:
    if run and run.status == "waiting" and (run.context or {}).get("waiting_callback") == "start_intensive":
        return {"next_message_at": "после нажатия кнопки «Начать интенсив»", "wait_interval": "кнопка находится в сообщении выше"}
    if not run or not run.next_action_at:
        return {"next_message_at": "по расписанию", "wait_interval": "точное время пока не определено"}
    next_at = run.next_action_at.replace(tzinfo=UTC) if run.next_action_at.tzinfo is None else run.next_action_at
    seconds = max(0, int((next_at - datetime.now(UTC)).total_seconds()))
    hours, remainder = divmod((seconds + 59) // 60, 60)
    wait = f"{hours} ч {remainder} мин" if hours and remainder else (f"{hours} ч" if hours else f"{max(1, remainder)} мин")
    return {"next_message_at": next_at.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y в %H:%M МСК"), "wait_interval": wait}


def _render_content(item: ContentItem, values: dict[str, str]) -> SimpleNamespace:
    channel_link = '<a href="https://t.me/Fitness_Talks">основной Telegram-канал</a>'
    body = replace_template_values(item.body_source, {**values, "channel_link": channel_link})
    return SimpleNamespace(code=item.code, title=item.title, body_source=body, source_format=item.source_format, media_kind=item.media_kind, media_path=item.media_path, telegram_file_id=item.telegram_file_id)


def send_system_content(
    session: Session,
    contact: Contact,
    content_code: str,
    sender,
    values: dict[str, str] | None = None,
    configuration: dict | None = None,
) -> str:
    item = session.scalar(select(ContentItem).where(ContentItem.code == content_code))
    if not item:
        raise RuntimeError(f"Missing start content: {content_code}")
    if not content_is_runtime_ready(item):
        raise RuntimeError(f"Start content is not owner-approved: {content_code}")
    rendered = _render_content(item, values or {})
    rendered, configuration = personalized_delivery(session, contact, rendered, configuration or {})
    log = ManualMessage(contact_id=contact.id, direction="out", body_source=rendered.body_source, status="pending", operator_email="system:start_router")
    session.add(log)
    try:
        log.platform_message_id = sender.send_content(contact.chat_id, rendered, configuration)
        log.status = "sent"
    except Exception:
        log.status = "failed"
        raise
    return str(log.platform_message_id)


def execute_start_decision(
    session: Session,
    contact: Contact,
    decision: StartDecision,
    welcome_run: SequenceRun | None,
    sender,
    sequence_code: str,
    target_step_key: str | None = None,
    update_id: str | None = None,
    entry_content_code: str = "tpl_intensive_entry_default",
    send_entry_circle: bool = True,
) -> SequenceRun | None:
    if decision.code == "masterclass_owned":
        stop_presale_runs_for_user(session, contact.user_id, reason="masterclass_owned")
        send_system_content(session, contact, decision.content_code, sender)
        return None
    if decision.code == "launch_welcome":
        if send_entry_circle:
            try:
                send_system_content(session, contact, "tpl_entry_circle", sender)
            except TelegramError as exc:
                if "VOICE_MESSAGES_FORBIDDEN" not in str(exc):
                    raise
                logger.info("Telegram recipient forbids video notes; skipping entry circle")
        send_system_content(
            session,
            contact,
            entry_content_code,
            sender,
            configuration={
                "buttons": [{"text": "Открыть интенсив", "url": "{{personal_intensive_url}}"}],
            },
        )
        run = start_run(session, contact.id, sequence_code)
        if target_step_key:
            run.current_step_key = target_step_key
        return run
    if decision.code == "intensive_complete":
        send_system_content(session, contact, decision.content_code, sender)
        return None
    if decision.code == "intensive_waiting":
        send_system_content(session, contact, decision.content_code, sender, _wait_values(welcome_run))
        return None
    if decision.code == "legacy_update":
        send_system_content(
            session,
            contact,
            decision.content_code,
            sender,
            configuration={
                "buttons": [
                    {"text": "Открыть интенсив", "url": "{{personal_intensive_url}}"},
                    {"text": "Читать программу Мастер-класса", "url": "{{personal_masterclass_url}}"},
                ],
            },
        )
    return None
