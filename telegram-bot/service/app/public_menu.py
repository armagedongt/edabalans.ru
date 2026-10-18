"""Public Telegram commands and their editable, owner-approved content slots."""
from __future__ import annotations

from html import escape
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content_formatting import content_is_runtime_ready, replace_template_values
from app.intensive_access import personal_tracking_values
from app.models import Contact, ContentItem
from app.temporary_entry import NAVIGATION_BODY, NAVIGATION_CODE, navigation_content


MENU_COMMANDS = (
    ("guide", 'Статья «Как сделать похудение проще!»'),
    ("mk", "Мастер-класс по изменению питания и пищевых привычек"),
    ("channel", "Открыть телеграм-канал"),
    ("contact", "Написать мне лично"),
    ("stop", "Остановить отправку сообщений в этом боте"),
)
COMMAND_ALIASES = {"/masterclass": "/mk", "/contacts": "/contact"}
NAVIGATION_CONTENT = (
    NAVIGATION_CODE, "Вход — навигационный закреп", NAVIGATION_BODY,
    "Показать полный канонический навигационный закреп без видео, кнопок и превью.",
)
COMMAND_CONTENT = {
    "/channel": NAVIGATION_CONTENT,
    "/contact": NAVIGATION_CONTENT,
    "/mk": (
        "tpl_menu_masterclass", "Меню — Мастер-класс",
        '<b>Мастер-класс по изменению питания и пищевых привычек</b>\n\n'
        'Подробное описание программы и отзывы участников — на моём сайте.\n\n'
        '<a href="{{personal_masterclass_url}}">похудение-это-есть.рф</a>',
        "Показать согласованный заголовок, программу и отзывы; ссылка в тексте, без превью и кнопок.",
    ),
    "/stop": (
        "tpl_menu_stop", "Меню — остановка сообщений",
        "Отправка новых сообщений в этот чат остановлена.\n\n"
        "Если захотите снова получать полезные посты и узнавать, что нового "
        "в моих программах, нажмите /resume.",
        "Подтвердить остановку и мягко предложить возобновление; не вызывать Start.",
    ),
    "/resume": (
        "tpl_menu_resume", "Меню — возобновление сообщений",
        "Отправка сообщений возобновлена.",
        "Подтвердить добровольное возобновление без повторного приветствия и старых сообщений.",
    ),
}


def seed_public_menu(session: Session) -> None:
    for code, title, body, purpose in COMMAND_CONTENT.values():
        if not session.scalar(select(ContentItem).where(ContentItem.code == code)):
            session.add(ContentItem(
                code=code, title=title, body_source=body,
                source_format="telegram_html", editorial_status="approved", status="published",
                purpose=purpose, writer_brief=f"Согласованный текст Сергея от 18.10.2026. {purpose}",
            ))
    session.flush()


def send_command_message(session: Session, contact: Contact, sender, command: str, settings) -> str:
    code = COMMAND_CONTENT[command][0]
    item = (navigation_content(session, "telegram") if code == NAVIGATION_CODE
            else session.scalar(select(ContentItem).where(ContentItem.code == code)))
    if not item or item.status != "published" or not content_is_runtime_ready(item):
        raise RuntimeError(f"Public menu content is not ready: {code}")
    variables = {
        "channel_url": "https://t.me/Fitness_Talks",
        "max_contact_url": escape(settings.max_contact_url, quote=True),
    }
    if command in {"/mk", "/channel", "/contact"}:
        variables.update(personal_tracking_values(
            session, user_id=contact.user_id, platform="telegram", public_url=settings.intensive_public_url,
        ))
    content = SimpleNamespace(
        code=item.code, title=item.title,
        body_source=replace_template_values(item.body_source, variables),
        media_kind=None, media_path=None, telegram_file_id=None,
    )
    return sender.send_content(contact.chat_id, content, {"link_preview": False})


def configure_commands(sender) -> None:
    commands = [{"command": command, "description": title} for command, title in MENU_COMMANDS]
    # Set both common scopes so an old Russian list cannot shadow the new menu.
    for language in ("", "ru"):
        sender.call("setMyCommands", {"commands": commands, "language_code": language})
    sender.call("setChatMenuButton", {"menu_button": {"type": "commands"}})


if __name__ == "__main__":
    from app.config import get_settings
    from app.telegram import TelegramClient
    config = get_settings()
    if not config.telegram_test_bot_token:
        raise SystemExit("Telegram bot token is not configured")
    configure_commands(TelegramClient(
        config.telegram_test_bot_token, proxy_url=config.telegram_proxy_url,
        api_base_url=config.telegram_api_base_url, gateway_token=config.telegram_gateway_token,
    ))
    print("Public menu configured")
