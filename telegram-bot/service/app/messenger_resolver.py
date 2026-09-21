from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BotInstance, Contact, CrmMessengerAccount


@dataclass(frozen=True)
class MessengerDestination:
    platform: str
    account_id: str
    contact_id: str
    platform_user_id: str
    chat_id: str


def preferred_destination(session: Session, user_id: str) -> MessengerDestination | None:
    """Resolve one exact active contact; never silently fall back to another channel."""
    accounts = list(
        session.scalars(
            select(CrmMessengerAccount)
            .where(
                CrmMessengerAccount.user_id == user_id,
                CrmMessengerAccount.linked_at.is_not(None),
                CrmMessengerAccount.is_deliverable.is_(True),
                CrmMessengerAccount.platform.in_(("telegram", "max")),
            )
            .order_by(
                CrmMessengerAccount.is_preferred.desc(),
                CrmMessengerAccount.linked_at.desc(),
                CrmMessengerAccount.id.desc(),
            )
        )
    )
    if not accounts:
        return None
    preferred = [account for account in accounts if account.is_preferred]
    if len(preferred) == 1:
        account = preferred[0]
    elif not preferred and len(accounts) == 1:
        account = accounts[0]
    else:
        return None
    bot_ids = select(BotInstance.id).where(
        BotInstance.code == "max"
        if account.platform == "max"
        else BotInstance.code != "max"
    )
    contact = session.scalar(
        select(Contact)
        .where(
            Contact.user_id == user_id,
            Contact.telegram_user_id == account.platform_user_id,
            Contact.status == "active",
            Contact.bot_instance_id.in_(bot_ids),
        )
        .order_by(Contact.last_seen_at.desc(), Contact.id.desc())
    )
    if contact is None:
        return None
    return MessengerDestination(
        platform=account.platform,
        account_id=account.id,
        contact_id=contact.id,
        platform_user_id=account.platform_user_id,
        chat_id=contact.chat_id,
    )
