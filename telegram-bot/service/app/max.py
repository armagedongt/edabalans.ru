"""MAX start adapter with identity, attribution and intensive access."""
from __future__ import annotations

import hashlib
import html
import re
import ssl
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from json import JSONDecodeError
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.account_credentials import generate_password, password_hash
from app.app_menu import APPS_PAYLOAD, app_request, send_menu
from app.content_formatting import content_body_for_telegram, replace_template_values
from app.customer_lifecycle import stop_presale_runs_for_user, stop_runs_for_contact
from app.intensive_access import (
    create_intensive_access_link,
    intensive_token,
    personal_tracking_values,
)
from app.models import (
    AccountCredential,
    AccountOnboarding,
    BotInstance,
    Contact,
    ContentItem,
    CrmAttributionEvent,
    CrmMessengerAccount,
    CrmTag,
    CrmUser,
    CrmUserTag,
    ManualMessage,
    MessengerLinkToken,
    TrackingLink,
    TrackingLinkAlias,
    TrackingLinkTag,
    TrackingEvent,
    UpdateReceipt,
    UserVariable,
)
from app.engine import advance_run, resume_callback
from app.seed import WELCOME_CODE
from app.start_router import execute_start_decision, inspect_start
from app.tracking import canonical_tag, resolve_start_payload


MAX_API_BASE = "https://platform-api2.max.ru"
MAX_CA_BUNDLE = Path(__file__).resolve().parent.parent / "certs" / "russian_trusted_ca.pem"
MAX_BOT_CODE = "max"
MAX_MESSAGE_TEXT_LIMIT = 4000
MAX_ONE_SHOT_CALLBACK_PREFIX = "mx1"
MAX_ONE_SHOT_VARIABLE_PREFIX = "max_one_shot:"
DEFAULT_MAX_CHANNEL_URL = "https://max.ru/id230409966750_biz"
DEFAULT_MAX_CONTACT_URL = "https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw"
HTML_LINK_PATTERN = re.compile(r'<a\s+href="([^"]+)"([^>]*)>(.*?)</a>', re.IGNORECASE | re.DOTALL)
MAX_ASSIGNMENT_ROUTES = {
    "iz1": (1, "tpl_max_forwarded_assignment_day1"),
    "iz2": (2, "tpl_max_forwarded_assignment_day2"),
    "iz3": (3, "tpl_max_forwarded_assignment_day3"),
}


class MaxClient:
    def __init__(
        self,
        token: str,
        transport: httpx.BaseTransport | None = None,
        bot_username: str = "",
        channel_url: str = DEFAULT_MAX_CHANNEL_URL,
        contact_url: str = DEFAULT_MAX_CONTACT_URL,
    ):
        self.token = token
        self.transport = transport
        self.bot_username = bot_username.strip().lstrip("@")
        self.channel_url = channel_url.strip()
        self.contact_url = contact_url.strip()

    def _platform_url(self, value: str) -> str:
        """Keep a MAX delivery inside MAX when shared copy contains Telegram URLs."""
        parsed = urlparse(value)
        if (parsed.hostname or "").casefold() not in {"t.me", "telegram.me"}:
            return value
        first_path = parsed.path.strip("/").split("/", 1)[0].casefold()
        if first_path == "fitness_talks_bot" and self.bot_username:
            query = f"?{parsed.query}" if parsed.query else ""
            return f"https://max.ru/{self.bot_username}{query}"
        if first_path == "fitness_talks":
            return self.channel_url
        if first_path == "fitnesssergey":
            return self.contact_url
        return value

    def _platform_text(self, value: str) -> str:
        """Localize shared Telegram/MAX HTML without changing its editorial copy."""
        def replace_link(match: re.Match[str]) -> str:
            href, attributes, label = match.groups()
            normalized_label = re.sub(r"<[^>]+>", "", label).strip().casefold()
            if "канал" in normalized_label and "max" in normalized_label:
                href = self.channel_url
            else:
                href = self._platform_url(href)
            return f'<a href="{html.escape(href, quote=True)}"{attributes}>{label}</a>'

        text_value = HTML_LINK_PATTERN.sub(replace_link, value)
        text_value = text_value.replace("Основной тг-канал", "Основной канал в MAX")
        text_value = text_value.replace("мой Telegram-канал", "мой канал в MAX")
        text_value = text_value.replace(
            "По любым вопросам @FitnessSergey",
            f'По любым вопросам — <a href="{html.escape(self.contact_url, quote=True)}">напишите мне в MAX</a>',
        )
        text_value = text_value.replace(
            "Любые вопросы — просто напишите мне в личные сообщения @FitnessSergey",
            f'Любые вопросы — просто <a href="{html.escape(self.contact_url, quote=True)}">напишите мне в MAX</a>',
        )
        text_value = text_value.replace(
            "пишите мне в личные сообщения → @FitnessSergey",
            f'<a href="{html.escape(self.contact_url, quote=True)}">пишите мне в личные сообщения в MAX</a>',
        )
        return text_value.replace(
            "@FitnessSergey",
            f'<a href="{html.escape(self.contact_url, quote=True)}">написать мне в MAX</a>',
        )

    def _client(self, timeout: float = 20) -> httpx.Client:
        client_options: dict[str, Any] = {"timeout": timeout}
        if self.transport is not None:
            client_options["transport"] = self.transport
        else:
            tls_context = ssl.create_default_context()
            tls_context.load_verify_locations(cafile=str(MAX_CA_BUNDLE))
            client_options["verify"] = tls_context
        return httpx.Client(**client_options)

    @staticmethod
    def _compact_html(text: str) -> str:
        def max_text_units(value: str) -> int:
            return len(value.encode("utf-16-le")) // 2

        text = re.sub(r"</?tg-spoiler>", "", text)
        text = re.sub(r"<tg-emoji[^>]*>|</tg-emoji>", "", text)
        while max_text_units(text) > MAX_MESSAGE_TEXT_LIMIT:
            before = text
            for tag in ("blockquote", "b", "i", "u", "s"):
                if max_text_units(text) <= MAX_MESSAGE_TEXT_LIMIT:
                    break
                text = re.sub(fr"</?{tag}(?:\s[^>]*)?>", "", text, count=2)
            if text == before:
                break
        if max_text_units(text) > MAX_MESSAGE_TEXT_LIMIT:
            raise RuntimeError(
                f"MAX message exceeds {MAX_MESSAGE_TEXT_LIMIT} UTF-16 units "
                f"({max_text_units(text)})"
            )
        return text

    def _upload_media_value(
        self,
        media_type: str,
        filename: str,
        value: Any,
    ) -> dict[str, Any]:
        with self._client(120) as client:
            upload = client.post(
                f"{MAX_API_BASE}/uploads",
                params={"type": media_type},
                headers={"Authorization": self.token},
            )
            upload.raise_for_status()
            upload_payload = upload.json()
            upload_url = str(upload_payload.get("url") or "")
            if not upload_url.startswith("https://"):
                raise RuntimeError("MAX did not return a media upload URL")
            result = client.post(upload_url, files={"data": (filename, value)})
            result.raise_for_status()
            try:
                result_payload = result.json() if result.content.strip() else {}
            except JSONDecodeError as exc:
                if not upload_payload.get("token"):
                    raise RuntimeError("MAX returned an unsupported media upload response") from exc
                result_payload = {}
        payload = dict(result_payload or {})
        if media_type == "image" and not payload.get("token"):
            photos = payload.get("photos")
            if isinstance(photos, dict):
                photo_token = next(
                    (
                        photo.get("token")
                        for photo in photos.values()
                        if isinstance(photo, dict) and photo.get("token")
                    ),
                    None,
                )
                if photo_token:
                    payload = {"token": photo_token}
        if not payload.get("token") and upload_payload.get("token"):
            payload["token"] = upload_payload["token"]
        if not payload.get("token"):
            raise RuntimeError("MAX did not return a media token")
        return payload

    def _upload_media(self, media_type: str, path: Path) -> dict[str, Any]:
        with path.open("rb") as stream:
            return self._upload_media_value(media_type, path.name, stream)

    def _upload_remote_image(self, url: str) -> dict[str, Any]:
        with self._client(120) as client:
            source = client.get(url)
            source.raise_for_status()
        filename = Path(urlparse(url).path).name or "image.jpg"
        return self._upload_media_value("image", filename, source.content)

    def send_html(
        self,
        user_id: str,
        text: str,
        *,
        button_text: str | None = None,
        button_url: str | None = None,
        callback_data: str | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "text": self._compact_html(self._platform_text(text)),
            "format": "html",
            "disable_link_preview": True,
        }
        if button_text and button_url and callback_data:
            raise ValueError("MAX button cannot be both a link and a callback")
        if button_text and (button_url or callback_data):
            button: dict[str, Any] = {
                "type": "link" if button_url else "callback",
                "text": button_text,
            }
            if button_url:
                button["url"] = self._platform_url(button_url)
            else:
                button["payload"] = callback_data
            body["attachments"] = [{
                "type": "inline_keyboard",
                "payload": {"buttons": [[button]]},
            }]
        with self._client() as client:
            response = client.post(
                f"{MAX_API_BASE}/messages",
                params={"user_id": user_id},
                headers={"Authorization": self.token},
                json=body,
            )
        response.raise_for_status()
        data = response.json()
        return str(data.get("message", {}).get("body", {}).get("mid", ""))

    def answer_callback(
        self,
        callback_id: str,
        *,
        replacement_text: str | None = None,
        notification: str = "",
    ) -> None:
        body: dict[str, Any] = {}
        if replacement_text is not None:
            body["message"] = {
                "text": self._compact_html(self._platform_text(replacement_text)),
                "format": "html",
                "disable_link_preview": True,
                "attachments": [],
            }
        if notification:
            body["notification"] = notification
        with self._client() as client:
            response = client.post(
                f"{MAX_API_BASE}/answers",
                params={"callback_id": callback_id},
                headers={"Authorization": self.token},
                json=body,
            )
        response.raise_for_status()
        result = response.json()
        if result.get("success") is False:
            raise RuntimeError(result.get("message") or "MAX callback answer failed")

    def send_content(self, user_id: str, content: Any, configuration: dict[str, Any]) -> str:
        text_value = self._compact_html(
            self._platform_text(content_body_for_telegram(content))
        )
        attachments: list[dict[str, Any]] = []
        remote_image_url: str | None = None
        media_path = str(getattr(content, "media_path", "") or "")
        media_kind = str(getattr(content, "media_kind", "") or "")
        if media_kind in {"photo", "video", "video_note"} and media_path:
            max_type = "image" if media_kind == "photo" else "video"
            if max_type == "image" and media_path.startswith(("https://", "http://")):
                remote_image_url = media_path
                payload = {"url": media_path}
            else:
                local_path = Path(media_path)
                if not local_path.is_file():
                    raise RuntimeError(f"MAX media file is unavailable: {media_path}")
                payload = self._upload_media(max_type, local_path)
            attachments.append({"type": max_type, "payload": payload})
        buttons = configuration.get("buttons") or []
        if buttons:
            rows = []
            for button in buttons:
                app_payload = str(button.get("max_app_payload") or "")
                if button.get("web_app") and app_payload and self.bot_username:
                    rows.append([{
                        "type": "open_app",
                        "text": button["text"],
                        "web_app": f"https://max.ru/{self.bot_username}",
                        "payload": app_payload,
                    }])
                    continue
                callback_data = button.get("callback_data")
                if callback_data:
                    rows.append([{
                        "type": "callback",
                        "text": button["text"],
                        "payload": str(callback_data),
                    }])
                    continue
                url = button.get("url") or (button.get("web_app") or {}).get("url")
                if not url:
                    raise RuntimeError("MAX sequence supports only link, callback and Mini App buttons")
                rows.append([{
                    "type": "link",
                    "text": button["text"],
                    "url": self._platform_url(str(url)),
                }])
            attachments.append({"type": "inline_keyboard", "payload": {"buttons": rows}})
        body: dict[str, Any] = {
            "text": text_value,
            "format": "html",
            "disable_link_preview": bool(not configuration.get("link_preview", False)),
        }
        if attachments:
            body["attachments"] = attachments
        with self._client(120 if media_path else 20) as client:
            response = client.post(
                f"{MAX_API_BASE}/messages",
                params={"user_id": user_id},
                headers={"Authorization": self.token},
                json=body,
            )
            if (
                remote_image_url
                and response.status_code == 400
                and "Failed to upload image" in response.text
            ):
                attachments[0]["payload"] = self._upload_remote_image(remote_image_url)
                response = client.post(
                    f"{MAX_API_BASE}/messages",
                    params={"user_id": user_id},
                    headers={"Authorization": self.token},
                    json=body,
                )
        response.raise_for_status()
        data = response.json()
        return str(data.get("message", {}).get("body", {}).get("mid", ""))

    def subscription_status(self, _user_id: str) -> None:
        # MAX has no Telegram-channel membership to check. Returning unknown
        # selects the full in-bot material without creating subscription tags.
        return None


def _max_bot(session: Session, username: str) -> BotInstance:
    bot = session.scalar(select(BotInstance).where(BotInstance.code == MAX_BOT_CODE))
    if bot:
        if username:
            bot.username = username.lstrip("@")
        return bot
    bot = BotInstance(
        code=MAX_BOT_CODE,
        username=username.lstrip("@") or "max-bot",
        display_name="MAX-бот",
        token_env_name="MAX_BOT_TOKEN",
        is_production=False,
        is_active=True,
    )
    session.add(bot)
    session.flush()
    return bot


def _receipt_id(update: dict[str, Any]) -> str:
    callback = update.get("callback") or {}
    user = update.get("user") or callback.get("user") or {}
    raw = "|".join((
        str(update.get("update_type", "")),
        str(update.get("timestamp", "")),
        str(user.get("user_id", "")),
        str(update.get("payload", "") or callback.get("payload", "")),
        str(callback.get("callback_id", "")),
    ))
    return f"max:{hashlib.sha256(raw.encode()).hexdigest()[:56]}"


def _one_shot_payload(token: str, message_index: int) -> str:
    return f"{MAX_ONE_SHOT_CALLBACK_PREFIX}:{token}:{message_index}"


def _parse_one_shot_payload(payload: str) -> tuple[str, int] | None:
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != MAX_ONE_SHOT_CALLBACK_PREFIX:
        return None
    token = parts[1]
    if not re.fullmatch(r"[a-f0-9]{20}", token):
        return None
    try:
        message_index = int(parts[2])
    except ValueError:
        return None
    return token, message_index


def start_max_one_shot_chain(
    session: Session,
    contact: Contact,
    sender: MaxClient,
    messages: list[str],
) -> dict[str, Any]:
    if not messages:
        raise ValueError("MAX one-shot chain needs at least one message")
    for message in messages:
        MaxClient._compact_html(message)

    token = uuid.uuid4().hex[:20]
    variable = UserVariable(
        contact_id=contact.id,
        key=f"{MAX_ONE_SHOT_VARIABLE_PREFIX}{token}",
        value={
            "version": 1,
            "messages": messages,
            "expected_index": 0,
            "status": "pending",
            "message_ids": [],
        },
    )
    session.add(variable)
    session.commit()

    try:
        message_id = sender.send_html(
            contact.chat_id,
            messages[0],
            button_text="Завершить тест" if len(messages) == 1 else "Читать дальше",
            callback_data=_one_shot_payload(token, 0),
        )
    except Exception as exc:
        variable = session.scalar(
            select(UserVariable)
            .where(UserVariable.id == variable.id)
            .with_for_update()
        )
        variable.value = {**variable.value, "status": "error", "error": str(exc)}
        session.commit()
        raise

    variable = session.scalar(
        select(UserVariable)
        .where(UserVariable.id == variable.id)
        .with_for_update()
    )
    variable.value = {
        **variable.value,
        "status": "waiting",
        "message_ids": [message_id],
    }
    session.add(ManualMessage(
        contact_id=contact.id,
        direction="out",
        body_source=messages[0],
        status="sent",
        operator_email="system:max_one_shot_test",
        platform_message_id=message_id,
    ))
    session.commit()
    return {"token": token, "message_id": message_id, "messages": len(messages)}


def _handle_max_one_shot_callback(
    session: Session,
    *,
    contact: Contact,
    callback: dict[str, Any],
    sender: MaxClient,
) -> dict[str, Any] | None:
    parsed = _parse_one_shot_payload(str(callback.get("payload") or ""))
    if parsed is None:
        return None
    token, message_index = parsed
    variable = session.scalar(
        select(UserVariable)
        .where(
            UserVariable.contact_id == contact.id,
            UserVariable.key == f"{MAX_ONE_SHOT_VARIABLE_PREFIX}{token}",
        )
        .with_for_update()
    )
    callback_id = str(callback.get("callback_id") or "")
    if variable is None:
        sender.answer_callback(callback_id, notification="Эта кнопка уже неактивна")
        return {"ok": True, "duplicate": True, "one_shot": True}

    state = dict(variable.value or {})
    messages = list(state.get("messages") or [])
    expected_index = state.get("expected_index")
    if not 0 <= message_index < len(messages):
        sender.answer_callback(callback_id, notification="Эта кнопка уже неактивна")
        return {"ok": True, "duplicate": True, "one_shot": True}
    current_text = str(messages[message_index])
    if state.get("status") != "waiting" or expected_index != message_index:
        sender.answer_callback(
            callback_id,
            replacement_text=current_text,
            notification="Уже открыто",
        )
        return {"ok": True, "duplicate": True, "one_shot": True}

    # Hold the row lock until the old keyboard is removed and the next message is
    # accepted. A simultaneous second click then observes the advanced index and
    # cannot send the continuation twice.
    sender.answer_callback(callback_id, replacement_text=current_text)
    next_index = message_index + 1
    message_ids = list(state.get("message_ids") or [])
    if next_index < len(messages):
        next_message_id = sender.send_html(
            contact.chat_id,
            str(messages[next_index]),
            button_text=(
                "Завершить тест"
                if next_index == len(messages) - 1
                else "Читать дальше"
            ),
            callback_data=_one_shot_payload(token, next_index),
        )
        message_ids.append(next_message_id)
        state.update({
            "expected_index": next_index,
            "status": "waiting",
            "message_ids": message_ids,
        })
        session.add(ManualMessage(
            contact_id=contact.id,
            direction="out",
            body_source=str(messages[next_index]),
            status="sent",
            operator_email="system:max_one_shot_test",
            platform_message_id=next_message_id,
        ))
    else:
        state.update({"expected_index": None, "status": "completed"})
    variable.value = state
    session.add(TrackingEvent(
        contact_id=contact.id,
        user_id=contact.user_id,
        telegram_user_id=contact.telegram_user_id,
        event_type="max_one_shot_advanced",
        deduplication_key=f"max-one-shot:{token}:{message_index}",
        metadata_json={
            "messenger": "max",
            "message_index": message_index,
            "next_index": next_index if next_index < len(messages) else None,
        },
    ))
    session.commit()
    return {
        "ok": True,
        "one_shot": True,
        "completed": next_index >= len(messages),
        "next_index": next_index if next_index < len(messages) else None,
    }


def _ensure_contact(
    session: Session,
    bot: BotInstance,
    account: CrmMessengerAccount,
    user: dict[str, Any],
) -> Contact:
    platform_user_id = str(user["user_id"])
    contact = session.scalar(select(Contact).where(
        Contact.bot_instance_id == bot.id,
        Contact.telegram_user_id == platform_user_id,
    ))
    if contact is None:
        contact = Contact(
            bot_instance_id=bot.id,
            telegram_user_id=platform_user_id,
            chat_id=platform_user_id,
        )
        session.add(contact)
    contact.user_id = account.user_id
    contact.chat_id = platform_user_id
    contact.username = user.get("username")
    contact.first_name = user.get("name")
    contact.last_seen_at = datetime.now(UTC)
    contact.status = "active"
    session.flush()
    return contact


def _max_assignment_body(
    session: Session,
    *,
    content_code: str,
    user_id: str,
    intensive_public_url: str,
) -> str:
    item = session.scalar(select(ContentItem).where(ContentItem.code == content_code))
    if (
        item is None
        or item.status != "published"
        or item.editorial_status != "approved"
        or not (item.body_source or "").strip()
    ):
        raise RuntimeError(f"MAX assignment content is unavailable: {content_code}")
    body = item.body_source or ""
    if "{{personal_" in body:
        values = personal_tracking_values(
            session,
            user_id=user_id,
            platform="max",
            public_url=intensive_public_url,
        )
        body = replace_template_values(body, values)
    if "{{" in body:
        raise RuntimeError(f"MAX assignment has unresolved variables: {content_code}")
    if len(body) > MAX_MESSAGE_TEXT_LIMIT:
        raise RuntimeError(
            f"MAX assignment exceeds {MAX_MESSAGE_TEXT_LIMIT} characters: "
            f"{content_code} ({len(body)})"
        )
    return body


def _max_assignment_failure_status(exc: httpx.HTTPError) -> str:
    """Separate safe retries from calls whose delivery result is unknown."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
        return "retryable"
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 429:
            return "retryable"
        if 400 <= status_code < 500:
            return "failed"
        return "uncertain"
    return "uncertain"


def _record_max_assignment_failure(
    session: Session,
    delivery: TrackingEvent,
    exc: httpx.HTTPError,
) -> None:
    delivery.metadata_json = {
        **(delivery.metadata_json or {}),
        "max_delivery_status": _max_assignment_failure_status(exc),
        "max_delivery_error_type": type(exc).__name__,
    }
    session.commit()


def _send_max_assignment(
    session: Session,
    sender: MaxClient,
    *,
    platform_user_id: str,
    crm_user_id: str,
    content_code: str,
    intensive_public_url: str,
) -> str:
    body = _max_assignment_body(
        session,
        content_code=content_code,
        user_id=crm_user_id,
        intensive_public_url=intensive_public_url,
    )
    return sender.send_html(platform_user_id, body)


def _ensure_identity(session: Session, user: dict[str, Any]) -> tuple[CrmMessengerAccount, bool]:
    platform_user_id = str(user["user_id"])
    account = session.scalar(select(CrmMessengerAccount).where(
        CrmMessengerAccount.platform == "max",
        CrmMessengerAccount.platform_user_id == platform_user_id,
    ))
    now = datetime.now(UTC)
    created = account is None
    if account is None:
        crm_user = CrmUser(
            display_name=user.get("name") or user.get("username") or None,
            status="active",
            data_origin="native",
            first_seen_at=now,
        )
        session.add(crm_user)
        session.flush()
        account = CrmMessengerAccount(
            user_id=crm_user.id,
            platform="max",
            platform_user_id=platform_user_id,
            username=user.get("username"),
            first_name=user.get("name"),
            first_seen_at=now,
            last_seen_at=now,
            linked_at=now,
            source="max_bot",
        )
        session.add(account)
        session.flush()
    else:
        account.username = user.get("username")
        account.first_name = user.get("name")
        account.last_seen_at = now
    return account, created


def _is_disposable_identity(session: Session, user_id: str) -> bool:
    counts = session.execute(
        text(
            "SELECT "
            "(SELECT count(*) FROM user_emails WHERE user_id=:user_id) + "
            "(SELECT count(*) FROM user_accesses WHERE user_id=:user_id) + "
            "(SELECT count(*) FROM payments WHERE user_id=:user_id)"
        ),
        {"user_id": user_id},
    ).scalar_one()
    return int(counts or 0) == 0


def _existing_password_hint(credential: AccountCredential) -> str:
    created_at = credential.created_at or datetime.now(UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    issued_on = created_at.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y")
    return (
        f"Пароль уже приходил в этом чате при регистрации на сайте {issued_on}. "
        "Если не можете его найти, напишите мне."
    )


def _consume_account_link(
    session: Session,
    account: CrmMessengerAccount,
    payload: str,
    *,
    app_auth_secret: str,
    account_url: str,
) -> str:
    digest = hashlib.sha256(payload.encode("ascii", errors="ignore")).hexdigest()
    token = session.scalar(
        select(MessengerLinkToken)
        .where(MessengerLinkToken.token_hash == digest)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if token is None or token.platform != "max" or token.purpose != "account_credentials":
        return "Ссылка не найдена. Проверьте письмо или напишите мне."
    if token.consumed_at is not None:
        return "Эта ссылка уже использована. Если доступ не получен, напишите мне."
    expires_at = token.expires_at.replace(tzinfo=token.expires_at.tzinfo or UTC)
    if expires_at <= now:
        return "Срок действия ссылки истёк. Напишите мне, чтобы получить новую."
    onboarding = (
        session.scalar(
            select(AccountOnboarding)
            .where(AccountOnboarding.id == token.account_onboarding_id)
            .with_for_update()
        )
        if token.account_onboarding_id
        else None
    )
    if onboarding is not None and onboarding.claimed_at is not None:
        return "Данные для входа уже выданы в выбранном мессенджере. Если вы их потеряли, напишите мне."
    if account.user_id != token.user_id and not _is_disposable_identity(session, account.user_id):
        return "Этот аккаунт уже связан с другим личным кабинетом. Если это ошибка, напишите мне."

    account.user_id = token.user_id
    account.linked_at = now
    account.last_seen_at = now
    account.source = "account_onboarding"
    token.consumed_at = now
    if onboarding is not None:
        onboarding.status = "claimed"
        onboarding.claimed_platform = "max"
        onboarding.claimed_at = now
    session.add(
        TrackingEvent(
            user_id=token.user_id,
            telegram_user_id=account.platform_user_id,
            event_type="messenger_link_confirmed",
            deduplication_key=f"messenger-link-confirmed:{token.id}",
            metadata_json={"platform": "max", "purpose": token.purpose},
        )
    )
    stop_presale_runs_for_user(session, token.user_id, reason="messenger_link_confirmed")
    email = session.execute(
        text(
            "SELECT email_normalized FROM user_emails "
            "WHERE user_id=:user_id ORDER BY is_primary DESC, created_at LIMIT 1"
        ),
        {"user_id": token.user_id},
    ).scalar_one_or_none() or ""
    credential = session.get(AccountCredential, token.user_id)
    raw_password = None
    if credential is None:
        raw_password = generate_password()
        session.add(
            AccountCredential(
                user_id=token.user_id,
                password_hash=password_hash(raw_password, app_auth_secret),
                password_version=1,
                issued_via="max",
            )
        )
    if raw_password:
        return (
            "<b>Добро пожаловать! Доступ в личный кабинет готов.</b>\n\n"
            f"Логин: <code>{html.escape(email)}</code>\n"
            f"Пароль: <code>{raw_password}</code>\n\n"
            f'<a href="{html.escape(account_url, quote=True)}">Открыть личный кабинет</a>\n\n'
            "После первого входа сайт запомнит вас на этом устройстве."
        )
    return (
        "<b>Покупка добавлена в ваш личный кабинет.</b>\n\n"
        f"Логин: <code>{html.escape(email)}</code>\n"
        f'<a href="{html.escape(account_url, quote=True)}">Открыть личный кабинет</a>\n\n'
        + _existing_password_hint(credential)
    )


def _assign_first_touch(
    session: Session,
    account: CrmMessengerAccount,
    contact: Contact,
    is_first: bool,
    link: TrackingLink | None,
    alias: TrackingLinkAlias | None,
    session_tag_ids: list[str],
    raw_query: dict[str, str],
    payload_status: str,
    journey_context: dict[str, str],
    receipt_id: str,
    intensive_token_id: str,
) -> TrackingEvent:
    now = datetime.now(UTC)
    if is_first:
        account.main_scenario_seen_at = now
    if is_first and link:
        tag_ids = list(session.scalars(select(TrackingLinkTag.tag_id).where(
            TrackingLinkTag.tracking_link_id == link.id
        ))) + session_tag_ids
        for tag_id in dict.fromkeys(tag_ids):
            tag: CrmTag | None = canonical_tag(session, tag_id)
            if not tag:
                continue
            exists = session.scalar(select(CrmUserTag.id).where(
                CrmUserTag.user_id == account.user_id, CrmUserTag.tag_id == tag.id
            ))
            if not exists:
                session.add(CrmUserTag(user_id=account.user_id, tag_id=tag.id, source="max_first_touch"))
        session.add(CrmAttributionEvent(
            user_id=account.user_id,
            event_type="max_first_touch",
            source_raw=link.name,
            utm_source=raw_query.get("utm_source"),
            utm_medium=raw_query.get("utm_medium"),
            utm_campaign=raw_query.get("utm_campaign"),
            utm_content=raw_query.get("utm_content"),
            utm_term=raw_query.get("utm_term"),
            ref_code=alias.token if alias else None,
            occurred_at=now,
        ))
    session.add(CrmAttributionEvent(
        user_id=account.user_id,
        event_type="max_start" if payload_status != "unknown" else "max_start_unknown",
        source_raw=link.name if link else None,
        ref_code=alias.token if alias else None,
        occurred_at=now,
    ))
    tracking_event = TrackingEvent(
        tracking_link_id=link.id if link else None,
        contact_id=contact.id,
        alias_id=alias.id if alias else None,
        user_id=account.user_id,
        telegram_user_id=account.platform_user_id,
        event_type="start_first" if is_first else "start_repeat",
        metadata_json={
            "messenger": "max",
            "payload_status": payload_status,
            "raw_query": raw_query,
            **journey_context,
            "max_delivery_status": "pending",
            "max_intensive_token_id": intensive_token_id,
        },
        deduplication_key=f"{receipt_id}:tracking_start",
        occurred_at=now,
    )
    session.add(tracking_event)
    return tracking_event


def _deliver_welcome(
    session: Session,
    *,
    contact: Contact,
    is_first: bool,
    sender: MaxClient,
    link: TrackingLink | None,
    raw_query: dict[str, str],
) -> tuple[str, str]:
    _, decision, welcome_run = inspect_start(session, contact, is_first)
    yandex_entry = any(
        marker in " ".join([
            str((raw_query or {}).get("utm_source") or ""),
            str((raw_query or {}).get("utm_medium") or ""),
            str(link.campaign if link else ""),
            str(link.placement if link else ""),
            str(link.name if link else ""),
        ]).casefold()
        for marker in ("yandex", "яндекс", "direct", "директ")
    )
    run = execute_start_decision(
        session,
        contact,
        decision,
        welcome_run,
        sender,
        WELCOME_CODE,
        link.target_step_key if link and link.route_kind == "published_step" else None,
        entry_content_code=(
            "tpl_intensive_entry_yandex" if yandex_entry else "tpl_intensive_entry_default"
        ),
        send_entry_circle=True,
    )
    if run:
        advance_run(session, run, sender)
    message_id = session.scalar(
        select(ManualMessage.platform_message_id)
        .where(
            ManualMessage.contact_id == contact.id,
            ManualMessage.direction == "out",
            ManualMessage.status == "sent",
            ManualMessage.body_source != "",
        )
        .order_by(ManualMessage.created_at.desc(), ManualMessage.id.desc())
        .limit(1)
    ) or ""
    return str(message_id), decision.code


def process_max_update(
    session: Session,
    update: dict[str, Any],
    *,
    bot_username: str,
    intensive_public_url: str,
    sender: MaxClient,
    app_auth_secret: str = "",
    account_url: str = "https://edabalans.ru/lk",
) -> dict[str, Any]:
    """Persist a MAX bot start and send a platform-bound intensive link."""
    update_type = str(update.get("update_type") or "")
    if update_type == "message_callback":
        callback = update.get("callback") or {}
        user = callback.get("user") or {}
        callback_id = str(callback.get("callback_id") or "")
        if not user.get("user_id") or not callback_id:
            return {"ok": True, "ignored": True}
        bot = _max_bot(session, bot_username)
        account, _ = _ensure_identity(session, user)
        contact = _ensure_contact(session, bot, account, user)
        result = _handle_max_one_shot_callback(
            session,
            contact=contact,
            callback=callback,
            sender=sender,
        )
        if result is None:
            callback_data = str(callback.get("payload") or "")
            run = resume_callback(session, contact.id, callback_data)
            message_body = (update.get("message") or {}).get("body") or {}
            replacement_text = message_body.get("text")
            sender.answer_callback(
                callback_id,
                replacement_text=str(replacement_text) if replacement_text is not None else None,
                notification="Продолжаем" if run else "Эта кнопка уже неактивна",
            )
            if run:
                advance_run(session, run, sender)
            result = {"ok": True, "callback": True, "resumed": bool(run)}
        receipt_id = _receipt_id(update)
        if session.get(UpdateReceipt, receipt_id) is None:
            session.add(UpdateReceipt(
                update_id=receipt_id,
                bot_instance_id=bot.id,
                update_type="max_message_callback",
            ))
            session.commit()
        return result
    if update_type in {"bot_stopped", "dialog_removed"}:
        user = update.get("user") or {}
        if not user.get("user_id"):
            return {"ok": True, "ignored": True}
        bot = _max_bot(session, bot_username)
        receipt_id = _receipt_id(update)
        if session.get(UpdateReceipt, receipt_id):
            return {"ok": True, "duplicate": True}
        session.add(UpdateReceipt(
            update_id=receipt_id,
            bot_instance_id=bot.id,
            update_type=f"max_{update_type}",
        ))
        platform_user_id = str(user["user_id"])
        contact = session.scalar(select(Contact).where(
            Contact.bot_instance_id == bot.id,
            Contact.telegram_user_id == platform_user_id,
        ))
        stopped_runs = 0
        if contact is not None:
            contact.status = "stopped"
            stopped_runs = stop_runs_for_contact(
                session,
                contact.id,
                reason=f"max_{update_type}",
            )
            session.add(TrackingEvent(
                contact_id=contact.id,
                user_id=contact.user_id,
                telegram_user_id=contact.telegram_user_id,
                event_type="bot_stopped",
                deduplication_key=f"{receipt_id}:bot_stopped",
                metadata_json={"messenger": "max", "update_type": update_type},
            ))
        session.commit()
        return {"ok": True, "stopped": True, "stopped_runs": stopped_runs}
    if update_type != "bot_started":
        return {"ok": True, "ignored": True}
    user = update.get("user") or {}
    if not user.get("user_id"):
        return {"ok": True, "ignored": True}

    bot = _max_bot(session, bot_username)
    receipt_id = _receipt_id(update)
    if session.get(UpdateReceipt, receipt_id):
        tracking_event = session.scalar(select(TrackingEvent).where(
            TrackingEvent.deduplication_key == f"{receipt_id}:tracking_start"
        ).with_for_update())
        metadata = dict(tracking_event.metadata_json or {}) if tracking_event else {}
        if tracking_event is None or metadata.get("max_delivery_status") == "sent":
            return {"ok": True, "duplicate": True}
        if metadata.get("max_delivery_kind") == "app_menu":
            delivery_status = str(metadata.get("max_delivery_status") or "pending")
            if delivery_status == "retryable":
                requested_app = app_request(
                    f"/start {str(metadata.get('app_payload') or APPS_PAYLOAD)}"
                )
                contact = (
                    session.get(Contact, tracking_event.contact_id)
                    if tracking_event.contact_id
                    else None
                )
                if requested_app is None or contact is None:
                    tracking_event.metadata_json = {
                        **metadata,
                        "max_delivery_status": "failed",
                    }
                    session.commit()
                    return {"ok": True, "duplicate": True, "delivery_status": "failed"}
                try:
                    message_id = send_menu(
                        session,
                        contact,
                        sender,
                        requested_app,
                        include_refresh=False,
                    )
                except httpx.HTTPError as exc:
                    _record_max_assignment_failure(session, tracking_event, exc)
                    raise
                tracking_event.metadata_json = {
                    **metadata,
                    "max_delivery_status": "sent",
                    "max_message_id": message_id,
                }
                session.commit()
                return {"ok": True, "retried": True, "applications": True}
            if delivery_status == "pending":
                tracking_event.metadata_json = {
                    **metadata,
                    "max_delivery_status": "uncertain",
                }
                session.commit()
                delivery_status = "uncertain"
            return {
                "ok": True,
                "duplicate": True,
                "applications": True,
                "delivery_status": delivery_status,
            }
        if metadata.get("max_delivery_kind") == "assignment":
            assignment_day = int(metadata["assignment_day"])
            if metadata.get("max_delivery_status") == "retryable":
                try:
                    message_id = _send_max_assignment(
                        session,
                        sender,
                        platform_user_id=str(user["user_id"]),
                        crm_user_id=tracking_event.user_id,
                        content_code=str(metadata["content_code"]),
                        intensive_public_url=intensive_public_url,
                    )
                except httpx.HTTPError as exc:
                    _record_max_assignment_failure(session, tracking_event, exc)
                    raise
                metadata.pop("max_delivery_kind", None)
                metadata.pop("max_delivery_error_type", None)
                tracking_event.metadata_json = {
                    **metadata,
                    "max_delivery_status": "sent",
                    "max_message_id": message_id,
                }
                session.commit()
                return {"ok": True, "retried": True, "assignment_day": assignment_day}
            if metadata.get("max_delivery_status") == "failed":
                return {
                    "ok": True,
                    "duplicate": True,
                    "delivery_status": "failed",
                    "assignment_day": assignment_day,
                }
            tracking_event.metadata_json = {
                **metadata,
                "max_delivery_status": "uncertain",
            }
            session.commit()
            return {
                "ok": True,
                "duplicate": True,
                "delivery_status": "uncertain",
                "assignment_day": assignment_day,
            }
        token_id = metadata.get("max_intensive_token_id")
        token_row = session.get(MessengerLinkToken, token_id) if token_id else None
        if token_row is None or token_row.consumed_at is not None:
            tracking_event.metadata_json = {
                **metadata,
                "max_delivery_status": "sent" if token_row is not None else "unrecoverable",
                "max_delivery_confirmed_by": "token_consumed" if token_row is not None else "token_missing",
            }
            session.commit()
            return {"ok": True, "duplicate": True}
        contact = session.get(Contact, tracking_event.contact_id) if tracking_event.contact_id else None
        if contact is None:
            tracking_event.metadata_json = {
                **(tracking_event.metadata_json or {}),
                "max_delivery_status": "unrecoverable",
                "max_delivery_error_type": "contact_missing",
            }
            session.commit()
            return {"ok": True, "duplicate": True}
        message_id, decision_code = _deliver_welcome(
            session,
            contact=contact,
            is_first=bool(metadata.get("is_first_scenario", True)),
            sender=sender,
            link=(
                session.get(TrackingLink, tracking_event.tracking_link_id)
                if tracking_event.tracking_link_id
                else None
            ),
            raw_query=dict(metadata.get("raw_query") or {}),
        )
        tracking_event.metadata_json = {
            **(tracking_event.metadata_json or {}),
            "max_delivery_status": "sent",
            "max_message_id": message_id,
            "max_start_decision": decision_code,
        }
        session.commit()
        return {"ok": True, "retried": True}

    payload = str(update.get("payload") or "")
    requested_app = app_request(f"/start {payload}")
    if requested_app is not None:
        session.add(
            UpdateReceipt(
                update_id=receipt_id,
                bot_instance_id=bot.id,
                update_type="max_app_menu_started",
            )
        )
        account, _ = _ensure_identity(session, user)
        contact = _ensure_contact(session, bot, account, user)
        delivery = TrackingEvent(
            contact_id=contact.id,
            user_id=account.user_id,
            telegram_user_id=account.platform_user_id,
            event_type="max_app_menu_delivery",
            deduplication_key=f"{receipt_id}:tracking_start",
            metadata_json={
                "messenger": "max",
                "max_delivery_kind": "app_menu",
                "max_delivery_status": "pending",
                "app_payload": payload,
            },
        )
        session.add(delivery)
        session.commit()
        try:
            message_id = send_menu(
                session,
                contact,
                sender,
                requested_app,
                include_refresh=False,
            )
        except httpx.HTTPError as exc:
            _record_max_assignment_failure(session, delivery, exc)
            raise
        delivery.metadata_json = {
            **(delivery.metadata_json or {}),
            "max_delivery_status": "sent",
            "max_message_id": message_id,
        }
        session.commit()
        return {
            "ok": True,
            "applications": True,
            "menu": requested_app == APPS_PAYLOAD,
            "message_id": message_id,
        }

    if payload.startswith("M"):
        session.add(
            UpdateReceipt(
                update_id=receipt_id,
                bot_instance_id=bot.id,
                update_type="max_account_started",
            )
        )
        account, _ = _ensure_identity(session, user)
        reply = _consume_account_link(
            session,
            account,
            payload,
            app_auth_secret=app_auth_secret,
            account_url=account_url,
        )
        _ensure_contact(session, bot, account, user)
        sender.send_html(str(user["user_id"]), reply)
        session.commit()
        return {"ok": True, "account_credentials": True}

    assignment = MAX_ASSIGNMENT_ROUTES.get(payload)
    if assignment is not None:
        day_number, content_code = assignment
        session.add(
            UpdateReceipt(
                update_id=receipt_id,
                bot_instance_id=bot.id,
                update_type="max_assignment_started",
            )
        )
        account, _ = _ensure_identity(session, user)
        # Render before committing the receipt so a personalized day-3 link is
        # persisted together with the pending delivery and is recoverable.
        body = _max_assignment_body(
            session,
            content_code=content_code,
            user_id=account.user_id,
            intensive_public_url=intensive_public_url,
        )
        delivery = TrackingEvent(
            user_id=account.user_id,
            telegram_user_id=account.platform_user_id,
            event_type="intensive_assignment_delivery",
            deduplication_key=f"{receipt_id}:tracking_start",
            metadata_json={
                "messenger": "max",
                "assignment_day": day_number,
                "content_code": content_code,
                "max_delivery_kind": "assignment",
                "max_delivery_status": "pending",
            },
        )
        session.add(delivery)
        session.commit()
        try:
            message_id = sender.send_html(str(user["user_id"]), body)
        except httpx.HTTPError as exc:
            delivery = session.scalar(
                select(TrackingEvent)
                .where(TrackingEvent.deduplication_key == f"{receipt_id}:tracking_start")
                .with_for_update()
            )
            _record_max_assignment_failure(session, delivery, exc)
            raise
        delivery = session.scalar(
            select(TrackingEvent)
            .where(TrackingEvent.deduplication_key == f"{receipt_id}:tracking_start")
            .with_for_update()
        )
        metadata = dict(delivery.metadata_json or {})
        metadata.pop("max_delivery_kind", None)
        delivery.metadata_json = {
            **metadata,
            "max_delivery_status": "sent",
            "max_message_id": message_id,
        }
        session.commit()
        return {"ok": True, "assignment_day": day_number}

    session.add(UpdateReceipt(update_id=receipt_id, bot_instance_id=bot.id, update_type="max_bot_started"))

    account, _ = _ensure_identity(session, user)
    contact = _ensure_contact(session, bot, account, user)
    is_first_scenario = account.main_scenario_seen_at is None
    link, alias, session_tag_ids, raw_query, payload_status, journey_context = resolve_start_payload(session, str(update.get("payload") or ""))
    intensive_token_id = str(uuid.uuid4())
    token = intensive_token(intensive_token_id)
    tracking_event = _assign_first_touch(
        session,
        account,
        contact,
        is_first_scenario,
        link,
        alias,
        session_tag_ids,
        raw_query,
        payload_status,
        journey_context,
        receipt_id,
        intensive_token_id,
    )
    create_intensive_access_link(
        session,
        user_id=account.user_id,
        platform="max",
        public_url=intensive_public_url,
        token=token,
        row_id=intensive_token_id,
    )
    # Persist the deterministic URL before the external call. If MAX accepts the
    # message but its response is lost, a webhook retry sends the same valid URL.
    session.commit()
    tracking_event = session.scalar(select(TrackingEvent).where(
        TrackingEvent.deduplication_key == f"{receipt_id}:tracking_start"
    ).with_for_update())
    message_id, decision_code = _deliver_welcome(
        session,
        contact=contact,
        is_first=is_first_scenario,
        sender=sender,
        link=link,
        raw_query=raw_query,
    )
    tracking_event.metadata_json = {
        **(tracking_event.metadata_json or {}),
        "max_delivery_status": "sent",
        "max_message_id": message_id,
        "max_start_decision": decision_code,
        "is_first_scenario": is_first_scenario,
    }
    session.commit()
    return {"ok": True, "intensive": True, "first_start": is_first_scenario}
