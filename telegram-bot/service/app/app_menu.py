from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from types import SimpleNamespace

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.content_formatting import content_is_runtime_ready
from app.models import Contact, ContentItem, CrmUser


APPS_PAYLOAD = "apps"
STRENGTH_ADMIN_PAYLOAD = "training_admin"
STRENGTH_ADMIN_CONTENT_CODE = "tpl_apps_strength_admin"
REFRESH_CALLBACK = "apps:refresh"
SUPPORT_URL = "https://t.me/FitnessSergey"


@dataclass(frozen=True)
class Application:
    code: str
    payload: str
    title: str
    url: str
    resource_codes: tuple[str, ...]


APPLICATIONS = (
    Application("dqs", "dqs", "Оценка качества питания", "https://edabalans.ru/dqs", ("dqs",)),
    Application("strength", "training", "Силовые тренировки", "https://edabalans.ru/training", ("strength", "ACCESS_STRENGTH")),
    Application("metabolism", "metabolism", "Калькулятор метаболизма", "https://edabalans.ru/metabolism", ("metabolism", "ACCESS_CALORIES")),
    Application("recipes", "recipes", "Калькулятор рецептов", "https://edabalans.ru/recipes", ("recipes", "ACCESS_RECIPES")),
)
APPLICATION_BY_PAYLOAD = {item.payload: item for item in APPLICATIONS}
REVEAL_EVENTS = {
    "dqs": {"app_revealed_dqs"},
    "strength": {"app_revealed_strength"},
    "metabolism": {"app_revealed_metabolism"},
    "recipes": {"app_revealed_recipes"},
}


def app_request(text: str) -> Application | str | None:
    normalized = (text or "").strip()
    if normalized.casefold() in {"/apps", "мои приложения"}:
        return APPS_PAYLOAD
    if not normalized.startswith("/start"):
        return None
    payload = normalized.partition(" ")[2].strip().casefold()
    if payload == APPS_PAYLOAD:
        return APPS_PAYLOAD
    if payload == STRENGTH_ADMIN_PAYLOAD:
        return STRENGTH_ADMIN_PAYLOAD
    return APPLICATION_BY_PAYLOAD.get(payload)


def entitled_applications(session: Session, user_id: str | None) -> list[Application]:
    if not user_id:
        return []
    user = session.get(CrmUser, user_id)
    if user is None or user.status != "active" or user.merged_into_user_id is not None:
        return []
    now = datetime.now(UTC)
    # These tables belong to the platform access module, not to the Telegram
    # service. Keep the integration read-only and out of this service's ORM
    # metadata so startup/tests never try to create or alter the shared tables.
    codes = set(session.execute(text("""
        SELECT r.code
        FROM user_accesses AS ua
        JOIN resources AS r ON r.id = ua.resource_id
        WHERE ua.user_id = :user_id
          AND r.status = 'active'
          AND ua.revoked_at IS NULL
          AND ua.paused_at IS NULL
          AND (ua.expires_at IS NULL OR ua.expires_at > :now)
    """), {"user_id": user_id, "now": now}).scalars().all())
    return [item for item in APPLICATIONS if codes.intersection(item.resource_codes)]


def available_applications(session: Session, user_id: str | None) -> list[Application]:
    entitled = entitled_applications(session, user_id)
    if not entitled:
        return []
    reveal_types = set(session.execute(text("""
        SELECT event_type
        FROM masterclass_events
        WHERE user_id = :user_id
    """), {"user_id": user_id}).scalars().all())
    if inspect(session.get_bind()).has_table("dqs_states"):
        legacy_dqs_state = session.execute(text("""
            SELECT start_date, days, source
            FROM dqs_states
            WHERE user_id = :user_id
            LIMIT 1
        """), {"user_id": user_id}).mappings().first()
    else:
        # Early legacy databases can legitimately lack this optional
        # compatibility table. Current reveal events remain canonical.
        legacy_dqs_state = None
    legacy_dqs_revealed = False
    if legacy_dqs_state and legacy_dqs_state["source"] != "admin_open":
        days = legacy_dqs_state["days"]
        if isinstance(days, str):
            try:
                days = json.loads(days)
            except json.JSONDecodeError:
                days = None
        legacy_dqs_revealed = bool(legacy_dqs_state["start_date"] or days)
    return [
        item
        for item in entitled
        if reveal_types.intersection(REVEAL_EVENTS[item.code])
        or (item.code == "dqs" and legacy_dqs_revealed)
    ]


def _content(body: str) -> SimpleNamespace:
    return SimpleNamespace(
        title="Мои приложения",
        body_source=body,
        source_format="telegram_html",
        media_kind=None,
        media_path=None,
        telegram_file_id=None,
    )


def _editable_content(session: Session, code: str) -> ContentItem:
    """Return only an owner-approved runtime content slot."""
    item = session.scalar(select(ContentItem).where(ContentItem.code == code))
    if not item:
        raise RuntimeError(f"Missing direct-trigger content: {code}")
    if not content_is_runtime_ready(item):
        raise RuntimeError(f"Direct-trigger content is not owner-approved: {code}")
    return item


def _app_button(item: Application) -> dict:
    button = {
        "text": item.title,
        "max_app_payload": item.payload,
    }
    if item.code == "dqs":
        button["url"] = item.url
    else:
        button["web_app"] = {"url": item.url}
    return button


def menu_presentation(
    session: Session,
    contact: Contact,
    requested: Application | str = APPS_PAYLOAD,
    *,
    include_refresh: bool = True,
) -> tuple[SimpleNamespace, dict]:
    if requested == STRENGTH_ADMIN_PAYLOAD:
        query = f"&user={contact.user_id}" if contact.user_id else ""
        return (
            _editable_content(
                session,
                STRENGTH_ADMIN_CONTENT_CODE,
            ),
            {
                "buttons": [{
                    "text": "Открыть админку тренировок",
                    "web_app": {"url": f"https://edabalans.ru/admin/strength?mobile=1{query}"},
                }]
            },
        )
    entitled = entitled_applications(session, contact.user_id)
    available = available_applications(session, contact.user_id)
    if isinstance(requested, Application):
        if requested in available:
            available_copy = (
                "Приложение доступно. Нажмите кнопку ниже. Если вход в личный кабинет "
                "в браузере истёк, войдите обычным способом — после этого откроется DQS."
                if requested.code == "dqs"
                else "Приложение доступно. Нажмите кнопку ниже — оно откроется без "
                "повторного ввода логина и пароля."
            )
            return (
                _content(
                    f"<b>{requested.title}</b>\n\n{available_copy}"
                ),
                {"buttons": [_app_button(requested)]},
            )
        if requested in entitled:
            return (
                _content(
                    f"<b>{requested.title}</b>\n\n"
                    "Доступ уже есть. Приложение появится в «Моих приложениях» после соответствующего материала Мастер-класса."
                ),
                {"buttons": [{"text": "Открыть Мастер-класс", "url": "https://похудение-это-есть.рф/lk"}]},
            )
        return (
            _content(
                f"<b>{requested.title}</b>\n\n"
                "У вас пока нет доступа к этому приложению. Если доступ должен быть — напишите мне."
            ),
            {"buttons": [{"text": "Написать мне", "url": SUPPORT_URL}]},
        )

    buttons = [_app_button(item) for item in available]
    if include_refresh:
        buttons.append({"text": "Обновить", "callback_data": REFRESH_CALLBACK})
    if available:
        body = (
            "Вот приложения, которые сейчас доступны вам.\n\n"
            "Если вы приобрели что-то ещё, нажмите «Обновить»."
        )
    elif entitled:
        body = (
            "Доступы уже есть. Приложения появятся здесь после соответствующих материалов Мастер-класса."
        )
    else:
        body = "У вас пока нет доступных приложений. Если доступ должен быть — напишите мне."
    if not available:
        buttons.append({"text": "Написать мне", "url": SUPPORT_URL})
    return _content(f"<b>Мои приложения</b>\n\n{body}"), {"buttons": buttons}


def send_menu(
    session: Session,
    contact: Contact,
    sender,
    requested: Application | str,
    *,
    include_refresh: bool = True,
) -> str:
    content, configuration = menu_presentation(
        session,
        contact,
        requested,
        include_refresh=include_refresh,
    )
    return sender.send_content(contact.chat_id, content, configuration)


def refresh_menu(session: Session, contact: Contact, sender, message_id: str) -> None:
    content, configuration = menu_presentation(session, contact, APPS_PAYLOAD)
    sender.edit_content(contact.chat_id, message_id, content, configuration)
