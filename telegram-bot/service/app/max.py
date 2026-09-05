"""MAX start adapter with identity, attribution and intensive access."""
from __future__ import annotations

import hashlib
import html
import re
import ssl
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.account_credentials import generate_password, password_hash
from app.content_formatting import content_body_for_telegram, replace_template_values
from app.customer_lifecycle import stop_presale_runs_for_user
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
)
from app.engine import advance_run
from app.seed import WELCOME_CODE
from app.start_router import execute_start_decision, inspect_start
from app.tracking import canonical_tag, resolve_start_payload


MAX_API_BASE = "https://platform-api2.max.ru"
MAX_CA_BUNDLE = Path(__file__).resolve().parent.parent / "certs" / "russian_trusted_ca.pem"
MAX_BOT_CODE = "max"
MAX_MESSAGE_TEXT_LIMIT = 4000
MAX_ASSIGNMENT_ROUTES = {
    "iz1": (1, "tpl_max_forwarded_assignment_day1"),
    "iz2": (2, "tpl_max_forwarded_assignment_day2"),
    "iz3": (3, "tpl_max_forwarded_assignment_day3"),
}


class MaxClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None):
        self.token = token
        self.transport = transport

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
        text = re.sub(r"</?tg-spoiler>", "", text)
        text = re.sub(r"<tg-emoji[^>]*>|</tg-emoji>", "", text)
        for tag in ("blockquote", "b", "i", "u", "s"):
            if len(text) <= MAX_MESSAGE_TEXT_LIMIT:
                break
            text = re.sub(fr"</?{tag}(?:\s[^>]*)?>", "", text, count=2)
        if len(text) > MAX_MESSAGE_TEXT_LIMIT:
            raise RuntimeError(
                f"MAX message exceeds {MAX_MESSAGE_TEXT_LIMIT} characters ({len(text)})"
            )
        return text

    def _upload_media(self, media_type: str, path: Path) -> dict[str, Any]:
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
            with path.open("rb") as stream:
                result = client.post(upload_url, files={"data": (path.name, stream)})
            result.raise_for_status()
            result_payload = result.json()
        payload = dict(result_payload or {})
        if not payload.get("token") and upload_payload.get("token"):
            payload["token"] = upload_payload["token"]
        if not payload.get("token"):
            raise RuntimeError("MAX did not return a media token")
        return payload

    def send_html(
        self,
        user_id: str,
        text: str,
        *,
        button_text: str | None = None,
        button_url: str | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "text": self._compact_html(text),
            "format": "html",
            "disable_link_preview": True,
        }
        if button_text and button_url:
            body["attachments"] = [{
                "type": "inline_keyboard",
                "payload": {"buttons": [[{
                    "type": "link",
                    "text": button_text,
                    "url": button_url,
                }]]},
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

    def send_content(self, user_id: str, content: Any, configuration: dict[str, Any]) -> str:
        text_value = self._compact_html(content_body_for_telegram(content))
        attachments: list[dict[str, Any]] = []
        media_path = str(getattr(content, "media_path", "") or "")
        media_kind = str(getattr(content, "media_kind", "") or "")
        if media_kind in {"photo", "video", "video_note"} and media_path:
            max_type = "image" if media_kind == "photo" else "video"
            if max_type == "image" and media_path.startswith(("https://", "http://")):
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
                url = button.get("url") or (button.get("web_app") or {}).get("url")
                if not url:
                    raise RuntimeError("MAX sequence supports only link buttons")
                rows.append([{"type": "link", "text": button["text"], "url": url}])
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
    user = update.get("user") or {}
    raw = "|".join((
        str(update.get("update_type", "")),
        str(update.get("timestamp", "")),
        str(user.get("user_id", "")),
        str(update.get("payload", "")),
    ))
    return f"max:{hashlib.sha256(raw.encode()).hexdigest()[:56]}"


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
        return "Ссылка не найдена. Проверьте письмо или напишите Сергею."
    if token.consumed_at is not None:
        return "Эта ссылка уже использована. Если доступ не получен, напишите Сергею."
    expires_at = token.expires_at.replace(tzinfo=token.expires_at.tzinfo or UTC)
    if expires_at <= now:
        return "Срок действия ссылки истёк. Напишите Сергею, чтобы получить новую."
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
        return "Данные для входа уже выданы в выбранном мессенджере. Если вы их потеряли, напишите Сергею."
    if account.user_id != token.user_id and not _is_disposable_identity(session, account.user_id):
        return "Этот аккаунт уже связан с другим личным кабинетом. Если это ошибка, напишите Сергею."

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
        "Пароль не менялся. Если вы его потеряли, напишите Сергею."
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
    account_url: str = "https://go.похудение-это-есть.рф/lk",
) -> dict[str, Any]:
    """Persist a MAX bot start and send a platform-bound intensive link."""
    if update.get("update_type") != "bot_started":
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
    link, alias, session_tag_ids, raw_query, payload_status = resolve_start_payload(session, str(update.get("payload") or ""))
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
