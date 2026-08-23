from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.customer_lifecycle import stop_presale_runs_for_user
from app.models import (
    Contact,
    CrmMessengerAccount,
    MasterclassNotification,
    MessengerLinkToken,
    TrackingEvent,
)


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


def _queue_link_messages(session: Session, user_id: str, token_id: str) -> None:
    now = datetime.now(UTC)
    for kind, code in (
        ("messenger_identity", "tpl_postpurchase_identity"),
        ("messenger_questionnaire", "tpl_postpurchase_questionnaire"),
    ):
        key = f"messenger-link:{token_id}:{kind}"
        exists = session.scalar(
            select(MasterclassNotification.id).where(
                MasterclassNotification.user_id == user_id,
                MasterclassNotification.deduplication_key == key,
            )
        )
        if not exists:
            session.add(
                MasterclassNotification(
                    user_id=user_id,
                    notification_kind=kind,
                    content_code=code,
                    deduplication_key=key,
                    due_at=now,
                    payload={"messenger_link_token_id": token_id},
                )
            )


def consume_masterclass_link(
    session: Session,
    contact: Contact,
    telegram: dict,
    payload: str,
) -> tuple[bool, str]:
    """Consume an M-prefixed one-time link without allowing account takeover."""
    if not payload.startswith("M"):
        return False, "not_masterclass_link"
    digest = hashlib.sha256(payload.encode("ascii", errors="ignore")).hexdigest()
    token = session.scalar(
        select(MessengerLinkToken)
        .where(MessengerLinkToken.token_hash == digest)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if not token or token.platform != "telegram" or token.purpose != "link_account":
        return True, "Ссылка привязки не найдена. Вернитесь в Мастер-класс и создайте новую."
    if token.consumed_at:
        return True, "Эта ссылка уже использована. Если Telegram не привязался, создайте новую ссылку в Мастер-классе."
    if token.expires_at.replace(tzinfo=token.expires_at.tzinfo or UTC) <= now:
        return True, "Срок ссылки истёк. Вернитесь в Мастер-класс и нажмите привязку Telegram ещё раз."

    account = session.scalar(
        select(CrmMessengerAccount).where(
            CrmMessengerAccount.platform == "telegram",
            CrmMessengerAccount.platform_user_id == contact.telegram_user_id,
        )
    )
    if not account:
        return True, "Не удалось определить Telegram-аккаунт. Попробуйте открыть ссылку ещё раз."
    if account.user_id != token.user_id and not _is_disposable_identity(session, account.user_id):
        session.add(
            TrackingEvent(
                contact_id=contact.id,
                user_id=account.user_id,
                telegram_user_id=contact.telegram_user_id,
                event_type="messenger_link_conflict",
                deduplication_key=f"messenger-link-conflict:{token.id}",
                metadata_json={"target_user_id": token.user_id},
            )
        )
        return True, "Этот Telegram уже связан с другим клиентом. Напишите Сергею, чтобы безопасно проверить привязку."

    account.user_id = token.user_id
    account.username = telegram.get("username")
    account.first_name = telegram.get("first_name")
    account.last_seen_at = now
    account.linked_at = now
    account.source = "masterclass_link"
    contact.user_id = token.user_id
    token.consumed_at = now
    session.add(
        TrackingEvent(
            contact_id=contact.id,
            user_id=token.user_id,
            telegram_user_id=contact.telegram_user_id,
            event_type="messenger_link_confirmed",
            deduplication_key=f"messenger-link-confirmed:{token.id}",
            metadata_json={"platform": "telegram", "purpose": token.purpose},
        )
    )
    stop_presale_runs_for_user(
        session,
        token.user_id,
        reason="messenger_link_confirmed",
    )
    _queue_link_messages(session, token.user_id, token.id)
    return True, "Telegram привязан. Сейчас пришлю ваши данные и стартовую анкету отдельными сообщениями."
