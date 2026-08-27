"""Minimal MAX start adapter.

This adapter deliberately stops after identity, attribution and the maintenance
notice. It does not create a Telegram contact or start any Telegram sequence.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BotInstance,
    CrmAttributionEvent,
    CrmMessengerAccount,
    CrmTag,
    CrmUser,
    CrmUserTag,
    TrackingLink,
    TrackingLinkAlias,
    TrackingLinkTag,
    UpdateReceipt,
)
from app.tracking import canonical_tag, resolve_start_payload


MAX_API_BASE = "https://platform-api2.max.ru"
MAX_BOT_CODE = "max"
MAX_MAINTENANCE_MESSAGE = (
    "<b>Бот временно на небольшом ремонте</b> 🛠\n\n"
    "Я сейчас переношу сюда материалы и обновляю программу. "
    "Я уже сохранил, что вы заходили — повторно нажимать Start не нужно.\n\n"
    "В ближайшие пару дней всё доделаю и сам пришлю вам сообщение, когда бот снова будет готов.\n\n"
    "Если у вас есть вопрос или нужен доступ к уже купленным материалам, напишите мне."
)


class MaxClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None):
        self.token = token
        self.transport = transport

    def send_html(self, user_id: str, text: str) -> str:
        with httpx.Client(timeout=20, transport=self.transport) as client:
            response = client.post(
                f"{MAX_API_BASE}/messages",
                params={"user_id": user_id},
                headers={"Authorization": self.token},
                json={"text": text, "format": "html", "disable_link_preview": True},
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


def _assign_first_touch(
    session: Session,
    account: CrmMessengerAccount,
    created: bool,
    link: TrackingLink | None,
    alias: TrackingLinkAlias | None,
    session_tag_ids: list[str],
    raw_query: dict[str, str],
    payload_status: str,
) -> None:
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
        event_type="max_start_maintenance" if payload_status != "unknown" else "max_start_unknown",
        source_raw=link.name if link else None,
        ref_code=alias.token if alias else None,
        occurred_at=now,
    ))


def process_max_update(session: Session, update: dict[str, Any], *, bot_username: str, sender: MaxClient) -> dict[str, Any]:
    """Persist a MAX bot start and send only the temporary maintenance notice."""
    if update.get("update_type") != "bot_started":
        return {"ok": True, "ignored": True}
    user = update.get("user") or {}
    if not user.get("user_id"):
        return {"ok": True, "ignored": True}

    bot = _max_bot(session, bot_username)
    receipt_id = _receipt_id(update)
    if session.get(UpdateReceipt, receipt_id):
        return {"ok": True, "duplicate": True}
    session.add(UpdateReceipt(update_id=receipt_id, bot_instance_id=bot.id, update_type="max_bot_started"))

    account, created = _ensure_identity(session, user)
    link, alias, session_tag_ids, raw_query, payload_status = resolve_start_payload(session, str(update.get("payload") or ""))
    _assign_first_touch(session, account, created, link, alias, session_tag_ids, raw_query, payload_status)
    # A failed MAX delivery must make the webhook fail too, so MAX can retry it.
    # Commit only after the send succeeded; the receipt then suppresses normal retries.
    session.flush()
    sender.send_html(str(user["user_id"]), MAX_MAINTENANCE_MESSAGE)
    session.commit()
    return {"ok": True, "maintenance": True, "first_start": created}
