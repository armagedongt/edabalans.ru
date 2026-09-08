from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Contact, CrmUser


APPS_PAYLOAD = "apps"
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


def app_request(text: str) -> Application | str | None:
    normalized = (text or "").strip()
    if normalized.casefold() in {"/apps", "мои приложения"}:
        return APPS_PAYLOAD
    if not normalized.startswith("/start"):
        return None
    payload = normalized.partition(" ")[2].strip().casefold()
    if payload == APPS_PAYLOAD:
        return APPS_PAYLOAD
    return APPLICATION_BY_PAYLOAD.get(payload)


def available_applications(session: Session, user_id: str | None) -> list[Application]:
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
          AND (ua.expires_at IS NULL OR ua.expires_at > :now)
    """), {"user_id": user_id, "now": now}).scalars().all())
    return [item for item in APPLICATIONS if codes.intersection(item.resource_codes)]


def _content(body: str) -> SimpleNamespace:
    return SimpleNamespace(
        title="Мои приложения",
        body_source=body,
        source_format="telegram_html",
        media_kind=None,
        media_path=None,
        telegram_file_id=None,
    )


def _app_button(item: Application) -> dict:
    return {"text": item.title, "web_app": {"url": item.url}}


def menu_presentation(
    session: Session,
    contact: Contact,
    requested: Application | str = APPS_PAYLOAD,
) -> tuple[SimpleNamespace, dict]:
    available = available_applications(session, contact.user_id)
    if isinstance(requested, Application):
        if requested in available:
            return (
                _content(
                    f"<b>{requested.title}</b>\n\n"
                    "Приложение доступно. Нажмите кнопку ниже — оно откроется без повторного ввода логина и пароля."
                ),
                {"buttons": [_app_button(requested)]},
            )
        return (
            _content(
                f"<b>{requested.title}</b>\n\n"
                "У вас пока нет доступа к этому приложению. Если доступ должен быть — напишите мне."
            ),
            {"buttons": [{"text": "Написать мне", "url": SUPPORT_URL}]},
        )

    buttons = [_app_button(item) for item in available]
    buttons.append({"text": "Обновить", "callback_data": REFRESH_CALLBACK})
    body = (
        "Вот приложения, которые сейчас доступны вам.\n\n"
        "Если вы приобрели что-то ещё, нажмите «Обновить»."
        if available
        else "У вас пока нет доступных приложений. Если доступ должен быть — напишите мне."
    )
    if not available:
        buttons.append({"text": "Написать мне", "url": SUPPORT_URL})
    return _content(f"<b>Мои приложения</b>\n\n{body}"), {"buttons": buttons}


def send_menu(session: Session, contact: Contact, sender, requested: Application | str) -> str:
    content, configuration = menu_presentation(session, contact, requested)
    return sender.send_content(contact.chat_id, content, configuration)


def refresh_menu(session: Session, contact: Contact, sender, message_id: str) -> None:
    content, configuration = menu_presentation(session, contact, APPS_PAYLOAD)
    sender.edit_content(contact.chat_id, message_id, content, configuration)
