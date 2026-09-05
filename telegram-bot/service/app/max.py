"""MAX start adapter with identity, attribution and intensive access."""
from __future__ import annotations

import hashlib
import html
import ssl
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.account_credentials import generate_password, password_hash
from app.customer_lifecycle import stop_presale_runs_for_user
from app.intensive_access import (
    create_intensive_access_link,
    intensive_access_url,
    intensive_token,
)
from app.models import (
    AccountCredential,
    AccountOnboarding,
    BotInstance,
    CrmAttributionEvent,
    CrmMessengerAccount,
    CrmTag,
    CrmUser,
    CrmUserTag,
    MessengerLinkToken,
    TrackingLink,
    TrackingLinkAlias,
    TrackingLinkTag,
    TrackingEvent,
    UpdateReceipt,
)
from app.tracking import canonical_tag, resolve_start_payload


MAX_API_BASE = "https://platform-api2.max.ru"
MAX_CA_BUNDLE = Path(__file__).resolve().parent.parent / "certs" / "russian_trusted_ca.pem"
MAX_BOT_CODE = "max"
MAX_INTENSIVE_MESSAGE = (
    "<b>Бесплатный интенсив «Последнее похудение»</b>\n\n"
    "Нажмите кнопку ниже, чтобы открыть первый день."
)


class MaxClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None):
        self.token = token
        self.transport = transport

    def send_html(
        self,
        user_id: str,
        text: str,
        *,
        button_text: str | None = None,
        button_url: str | None = None,
    ) -> str:
        body: dict[str, Any] = {"text": text, "format": "html", "disable_link_preview": True}
        if button_text and button_url:
            body["attachments"] = [{
                "type": "inline_keyboard",
                "payload": {"buttons": [[{
                    "type": "link",
                    "text": button_text,
                    "url": button_url,
                }]]},
            }]
        client_options: dict[str, Any] = {"timeout": 20}
        if self.transport is not None:
            client_options["transport"] = self.transport
        else:
            tls_context = ssl.create_default_context()
            tls_context.load_verify_locations(cafile=str(MAX_CA_BUNDLE))
            client_options["verify"] = tls_context
        with httpx.Client(**client_options) as client:
            response = client.post(
                f"{MAX_API_BASE}/messages",
                params={"user_id": user_id},
                headers={"Authorization": self.token},
                json=body,
            )
        response.raise_for_status()
        data = response.json()
        return str(data.get("message", {}).get("body", {}).get("mid", ""))


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


def _send_intensive(sender: MaxClient, user_id: str, intensive_url: str) -> str:
    return sender.send_html(
        user_id,
        MAX_INTENSIVE_MESSAGE,
        button_text="Открыть первый день",
        button_url=intensive_url,
    )


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
    created: bool,
    link: TrackingLink | None,
    alias: TrackingLinkAlias | None,
    session_tag_ids: list[str],
    raw_query: dict[str, str],
    payload_status: str,
    receipt_id: str,
    intensive_token_id: str,
) -> TrackingEvent:
    now = datetime.now(UTC)
    if created and link:
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
        alias_id=alias.id if alias else None,
        user_id=account.user_id,
        telegram_user_id=account.platform_user_id,
        event_type="start_first" if created else "start_repeat",
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
        if tracking_event is None or (tracking_event.metadata_json or {}).get("max_delivery_status") == "sent":
            return {"ok": True, "duplicate": True}
        token_id = (tracking_event.metadata_json or {}).get("max_intensive_token_id")
        token_row = session.get(MessengerLinkToken, token_id) if token_id else None
        if token_row is None or token_row.consumed_at is not None:
            tracking_event.metadata_json = {
                **(tracking_event.metadata_json or {}),
                "max_delivery_status": "sent" if token_row is not None else "unrecoverable",
                "max_delivery_confirmed_by": "token_consumed" if token_row is not None else "token_missing",
            }
            session.commit()
            return {"ok": True, "duplicate": True}
        token = intensive_token(token_id)
        intensive_url = intensive_access_url(intensive_public_url, token)
        message_id = _send_intensive(sender, str(user["user_id"]), intensive_url)
        tracking_event.metadata_json = {
            **(tracking_event.metadata_json or {}),
            "max_delivery_status": "sent",
            "max_message_id": message_id,
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

    session.add(UpdateReceipt(update_id=receipt_id, bot_instance_id=bot.id, update_type="max_bot_started"))

    account, created = _ensure_identity(session, user)
    link, alias, session_tag_ids, raw_query, payload_status = resolve_start_payload(session, str(update.get("payload") or ""))
    intensive_token_id = str(uuid.uuid4())
    token = intensive_token(intensive_token_id)
    tracking_event = _assign_first_touch(
        session,
        account,
        created,
        link,
        alias,
        session_tag_ids,
        raw_query,
        payload_status,
        receipt_id,
        intensive_token_id,
    )
    intensive_url, _ = create_intensive_access_link(
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
    message_id = _send_intensive(sender, str(user["user_id"]), intensive_url)
    tracking_event.metadata_json = {
        **(tracking_event.metadata_json or {}),
        "max_delivery_status": "sent",
        "max_message_id": message_id,
    }
    session.commit()
    return {"ok": True, "intensive": True, "first_start": created}
