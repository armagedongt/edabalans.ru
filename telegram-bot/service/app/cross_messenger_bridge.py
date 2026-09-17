"""Persistent mapping and safe display formatting for shared practice chats."""
from __future__ import annotations

from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    MessagingBridgeDelivery,
    MessagingBridgeMessage,
    MessagingBridgePair,
    MessagingBridgeReceipt,
)


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


def _telegram_author(message: dict) -> str:
    author = message.get("from") or {}
    return str(author.get("first_name") or author.get("username") or "Участник")


def _max_author(message: dict) -> str:
    author = message.get("sender") or {}
    return str(author.get("name") or author.get("first_name") or author.get("username") or "Участник")


def _telegram_text(message: dict) -> str:
    return str(message.get("text") or message.get("caption") or "")


def _max_text(message: dict) -> str:
    return str((message.get("body") or {}).get("text") or "")


def _register_receipt(session: Session, platform: str, event_key: str) -> bool:
    existing = session.scalar(
        select(MessagingBridgeReceipt).where(
            MessagingBridgeReceipt.platform == platform,
            MessagingBridgeReceipt.event_key == event_key,
        )
    )
    if existing is not None:
        return False
    session.add(MessagingBridgeReceipt(platform=platform, event_key=event_key))
    return True


def _delivery(session: Session, message: MessagingBridgeMessage, target_platform: str, payload: dict) -> MessagingBridgeDelivery:
    delivery = MessagingBridgeDelivery(
        message_id=message.id,
        target_platform=target_platform,
        payload=payload,
    )
    session.add(delivery)
    return delivery


def _failed_delivery(session: Session, message: MessagingBridgeMessage) -> MessagingBridgeDelivery | None:
    return session.scalar(
        select(MessagingBridgeDelivery).where(
            MessagingBridgeDelivery.message_id == message.id,
            MessagingBridgeDelivery.status == "failed",
        )
    )


def _retry_failed_delivery(session: Session, message: MessagingBridgeMessage, sender) -> bool:
    """Retry one persisted outbound attempt when its source event is redelivered."""
    delivery = _failed_delivery(session, message)
    if delivery is None or delivery.attempts >= 3:
        return False
    payload = dict(delivery.payload or {})
    try:
        if delivery.target_platform == "max":
            counterpart_id = _sender(sender).send_chat_html(
                str(payload["chat_id"]),
                str(payload["text"]),
                reply_to_message_id=payload.get("reply_to_message_id"),
            )
            message.max_message_id = counterpart_id
        elif delivery.target_platform == "telegram":
            counterpart_id = _sender(sender).send_html_message(
                str(payload["chat_id"]),
                str(payload["text"]),
                reply_to_message_id=payload.get("reply_to_message_id"),
            )
            message.telegram_message_id = counterpart_id
        else:
            return False
    except Exception as exc:
        delivery.attempts += 1
        delivery.error_message = str(exc)
        session.commit()
        raise
    delivery.status = "delivered"
    delivery.attempts += 1
    delivery.error_message = None
    session.commit()
    return True


def _sender(value):
    """Delay construction of a platform client until a paired update needs it."""
    return value() if callable(value) else value


def is_telegram_pair_update(session: Session, update: dict) -> bool:
    """Identify an update addressed to a configured pair without delivering it."""
    message = next(
        (
            update.get(name)
            for name in ("channel_post", "message", "edited_channel_post", "edited_message")
            if update.get(name)
        ),
        None,
    )
    if not message:
        return False
    chat_id = str((message.get("chat") or {}).get("id") or "")
    return telegram_pair(session, chat_id) is not None


def process_telegram_update(session: Session, update: dict, max_sender) -> dict | None:
    """Mirror a text post or practice-chat message from Telegram to MAX.

    Returning ``None`` lets the existing Telegram lifecycle process its own
    private-bot updates unchanged.
    """
    event_name = next(
        (name for name in ("channel_post", "message", "edited_channel_post", "edited_message") if update.get(name)),
        None,
    )
    if event_name is None:
        return None
    message = update[event_name]
    chat_id = str((message.get("chat") or {}).get("id") or "")
    pair = telegram_pair(session, chat_id)
    if pair is None:
        return None
    if chat_id == pair.telegram_practice_chat_id and bool((message.get("from") or {}).get("is_bot")):
        return {"ok": True, "bridge": "own_bot"}
    message_id = str(message.get("message_id") or "")
    update_id = str(update.get("update_id") or "")
    if not message_id or not update_id:
        return {"ok": True, "bridge": "ignored"}
    if not _register_receipt(session, "telegram", update_id):
        mapped = mapped_telegram_message(session, pair.id, message_id)
        if mapped is not None and _retry_failed_delivery(session, mapped, max_sender):
            return {"ok": True, "bridge": "retried", "target": "max"}
        return {"ok": True, "bridge": "duplicate"}

    mapped = mapped_telegram_message(session, pair.id, message_id)
    if event_name.startswith("edited_"):
        if mapped is None or mapped.source_platform != "telegram" or not pair.sync_edits:
            session.commit()
            return {"ok": True, "bridge": "ignored_edit"}
        text = _telegram_text(message)
        if not text:
            session.commit()
            return {"ok": True, "bridge": "unsupported_edit"}
        rendered = text if mapped.kind == "post" else mirror_text("telegram", mapped.source_author_name or "Участник", text)
        try:
            _sender(max_sender).edit_chat_html(mapped.max_message_id, rendered)
        except Exception:
            session.rollback()
            raise
        session.commit()
        return {"ok": True, "bridge": "edited"}
    if mapped is not None:
        session.commit()
        return {"ok": True, "bridge": "own_mirror"}

    is_post = chat_id == pair.telegram_channel_id
    text = _telegram_text(message)
    if not text:
        session.commit()
        return {"ok": True, "bridge": "unsupported_media_pending"}
    parent = None
    if not is_post:
        reply = message.get("reply_to_message") or {}
        reply_id = str(reply.get("message_id") or "")
        if reply_id:
            parent = mapped_telegram_message(session, pair.id, reply_id)
    author = "Сергей" if is_post else _telegram_author(message)
    mapped = MessagingBridgeMessage(
        pair_id=pair.id,
        kind="post" if is_post else "practice",
        telegram_message_id=message_id,
        source_platform="telegram",
        source_author_name=author,
        parent_message_id=parent.id if parent else None,
    )
    session.add(mapped)
    session.flush()
    target = pair.max_channel_id if is_post else pair.max_practice_chat_id
    rendered = text if is_post else mirror_text("telegram", author, text)
    delivery = _delivery(
        session,
        mapped,
        "max",
        {"chat_id": target, "text": rendered, "reply_to_message_id": parent.max_message_id if parent else None},
    )
    session.commit()
    try:
        max_id = _sender(max_sender).send_chat_html(target, rendered, reply_to_message_id=parent.max_message_id if parent else None)
    except Exception as exc:
        delivery = session.get(MessagingBridgeDelivery, delivery.id)
        delivery.status = "failed"
        delivery.attempts += 1
        delivery.error_message = str(exc)
        session.commit()
        raise
    mapped = session.get(MessagingBridgeMessage, mapped.id)
    mapped.max_message_id = max_id
    delivery = session.get(MessagingBridgeDelivery, delivery.id)
    delivery.status = "delivered"
    delivery.attempts += 1
    session.commit()
    return {"ok": True, "bridge": "mirrored", "target": "max"}


def process_max_update(session: Session, update: dict, telegram_sender) -> dict | None:
    """Mirror a text message from a MAX practice chat to Telegram."""
    update_type = str(update.get("update_type") or "")
    if update_type not in {"message_created", "message_edited", "message_removed"}:
        return None
    message = update.get("message") or {}
    body = message.get("body") or {}
    message_id = str(body.get("mid") or update.get("message_id") or "")
    chat_id = str((message.get("recipient") or {}).get("chat_id") or update.get("chat_id") or "")
    pair = max_pair(session, chat_id)
    if pair is None:
        return None
    if chat_id != pair.max_practice_chat_id:
        return {"ok": True, "bridge": "ignored_channel"}
    if bool((message.get("sender") or {}).get("is_bot")):
        return {"ok": True, "bridge": "own_bot"}
    timestamp = str(update.get("timestamp") or "")
    if not message_id:
        return {"ok": True, "bridge": "unsupported_payload"}
    if not _register_receipt(session, "max", f"{update_type}:{message_id}:{timestamp}"):
        mapped = mapped_max_message(session, pair.id, message_id)
        if mapped is not None and _retry_failed_delivery(session, mapped, telegram_sender):
            return {"ok": True, "bridge": "retried", "target": "telegram"}
        return {"ok": True, "bridge": "duplicate"}
    mapped = mapped_max_message(session, pair.id, message_id)
    if update_type == "message_removed":
        if mapped is None or mapped.source_platform != "max" or not pair.sync_deletions:
            session.commit()
            return {"ok": True, "bridge": "ignored_remove"}
        _sender(telegram_sender).delete_message(pair.telegram_practice_chat_id, mapped.telegram_message_id)
        session.commit()
        return {"ok": True, "bridge": "removed"}
    if update_type == "message_edited":
        if mapped is None or mapped.source_platform != "max" or not pair.sync_edits:
            session.commit()
            return {"ok": True, "bridge": "ignored_edit"}
        text = _max_text(message)
        if not text:
            session.commit()
            return {"ok": True, "bridge": "unsupported_edit"}
        _sender(telegram_sender).edit_html_message(
            pair.telegram_practice_chat_id,
            mapped.telegram_message_id,
            mirror_text("max", mapped.source_author_name or "Участник", text),
        )
        session.commit()
        return {"ok": True, "bridge": "edited"}
    if mapped is not None:
        session.commit()
        return {"ok": True, "bridge": "own_mirror"}
    text = _max_text(message)
    if not text:
        session.commit()
        return {"ok": True, "bridge": "unsupported_media_pending"}
    link = message.get("link") or {}
    parent = mapped_max_message(session, pair.id, str(link.get("mid") or "")) if link.get("type") == "reply" else None
    author = _max_author(message)
    mapped = MessagingBridgeMessage(
        pair_id=pair.id,
        kind="practice",
        max_message_id=message_id,
        source_platform="max",
        source_author_name=author,
        parent_message_id=parent.id if parent else None,
    )
    session.add(mapped)
    session.flush()
    rendered = mirror_text("max", author, text)
    delivery = _delivery(
        session,
        mapped,
        "telegram",
        {
            "chat_id": pair.telegram_practice_chat_id,
            "text": rendered,
            "reply_to_message_id": parent.telegram_message_id if parent else None,
        },
    )
    session.commit()
    try:
        telegram_id = _sender(telegram_sender).send_html_message(
            pair.telegram_practice_chat_id,
            rendered,
            reply_to_message_id=parent.telegram_message_id if parent else None,
        )
    except Exception as exc:
        delivery = session.get(MessagingBridgeDelivery, delivery.id)
        delivery.status = "failed"
        delivery.attempts += 1
        delivery.error_message = str(exc)
        session.commit()
        raise
    mapped = session.get(MessagingBridgeMessage, mapped.id)
    mapped.telegram_message_id = telegram_id
    delivery = session.get(MessagingBridgeDelivery, delivery.id)
    delivery.status = "delivered"
    delivery.attempts += 1
    session.commit()
    return {"ok": True, "bridge": "mirrored", "target": "telegram"}
