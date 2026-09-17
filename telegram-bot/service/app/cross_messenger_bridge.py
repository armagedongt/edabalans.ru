"""Persistent mapping and safe display formatting for shared practice chats."""
from __future__ import annotations

from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MessagingBridgeMessage, MessagingBridgePair


ACTIVE_PAIR_STATUSES = ("test", "active")


def mirror_text(source_platform: str, author_name: str, text: str) -> str:
    """Make a forwarded human message legible without exposing an account link."""
    platform_label = {"telegram": "Telegram", "max": "MAX"}.get(source_platform)
    if platform_label is None:
        raise ValueError("Unknown source platform")
    label = escape(author_name.strip() or "Участник")
    body = escape(text)
    return f"<b>Из {platform_label} · {label}</b>\n{body}" if body else f"<b>Из {platform_label} · {label}</b>"


def telegram_pair(session: Session, chat_id: str) -> MessagingBridgePair | None:
    return session.scalar(
        select(MessagingBridgePair)
        .where(
            MessagingBridgePair.status.in_(ACTIVE_PAIR_STATUSES),
            (MessagingBridgePair.telegram_channel_id == chat_id)
            | (MessagingBridgePair.telegram_practice_chat_id == chat_id),
        )
        .order_by(MessagingBridgePair.created_at.desc())
    )


def max_pair(session: Session, chat_id: str) -> MessagingBridgePair | None:
    return session.scalar(
        select(MessagingBridgePair)
        .where(
            MessagingBridgePair.status.in_(ACTIVE_PAIR_STATUSES),
            (MessagingBridgePair.max_channel_id == chat_id)
            | (MessagingBridgePair.max_practice_chat_id == chat_id),
        )
        .order_by(MessagingBridgePair.created_at.desc())
    )


def mapped_telegram_message(
    session: Session,
    pair_id: str,
    message_id: str,
) -> MessagingBridgeMessage | None:
    return session.scalar(
        select(MessagingBridgeMessage).where(
            MessagingBridgeMessage.pair_id == pair_id,
            MessagingBridgeMessage.telegram_message_id == message_id,
        )
    )


def mapped_max_message(
    session: Session,
    pair_id: str,
    message_id: str,
) -> MessagingBridgeMessage | None:
    return session.scalar(
        select(MessagingBridgeMessage).where(
            MessagingBridgeMessage.pair_id == pair_id,
            MessagingBridgeMessage.max_message_id == message_id,
        )
    )
