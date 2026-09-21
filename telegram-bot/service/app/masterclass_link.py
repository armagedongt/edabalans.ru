from __future__ import annotations

import hashlib
import html
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.customer_lifecycle import stop_presale_runs_for_user
from app.account_credentials import encrypt_password, generate_password, password_hash
from app.models import (
    AccountCredential,
    AccountOnboarding,
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


def _queue_link_messages(
    session: Session,
    user_id: str,
    token_id: str,
    platform_user_id: str,
) -> None:
    now = datetime.now(UTC)
    for position, (kind, code) in enumerate((
        ("messenger_identity", "tpl_postpurchase_identity"),
        ("messenger_questionnaire", "tpl_postpurchase_questionnaire"),
    )):
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
                    due_at=now + timedelta(seconds=position),
                    payload={
                        "messenger_link_token_id": token_id,
                        "target_platform": "telegram",
                        "target_platform_user_id": platform_user_id,
                    },
                )
            )


def _existing_password_hint(credential: AccountCredential) -> str:
    created_at = credential.created_at or datetime.now(UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    issued_on = created_at.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y")
    return (
        f"Пароль уже приходил в этом чате при регистрации на сайте {issued_on}. "
        "Если не можете его найти, напишите мне."
    )


def consume_masterclass_link(
    session: Session,
    contact: Contact,
    telegram: dict,
    payload: str,
    app_auth_secret: str = "",
    account_url: str = "https://edabalans.ru/lk",
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
    if not token or token.platform != "telegram" or token.purpose not in {"link_account", "account_credentials", "named_delivery"}:
        return True, "Ссылка привязки не найдена. Вернитесь в Мастер-класс и создайте новую."
    if token.consumed_at:
        return True, "Эта ссылка уже использована. Если Telegram не привязался, создайте новую ссылку в Мастер-классе."
    if token.expires_at.replace(tzinfo=token.expires_at.tzinfo or UTC) <= now:
        return True, "Срок ссылки истёк. Вернитесь в Мастер-класс и нажмите привязку Telegram ещё раз."
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
        return True, "Данные для входа уже выданы в выбранном мессенджере. Если вы их потеряли, напишите мне."
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT id FROM users WHERE id=:user_id FOR UPDATE"), {"user_id": token.user_id})

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
        return True, "Этот Telegram уже связан с другим клиентом. Напишите мне, чтобы я проверил привязку."

    account.user_id = token.user_id
    account.username = telegram.get("username")
    account.first_name = telegram.get("first_name")
    account.last_seen_at = now
    account.linked_at = now
    account.source = "account_onboarding" if token.purpose == "account_credentials" else "masterclass_link"
    account.is_deliverable = False
    account.is_preferred = False
    for previous in session.scalars(select(CrmMessengerAccount).where(
        CrmMessengerAccount.user_id == token.user_id,
        CrmMessengerAccount.platform == "telegram",
        CrmMessengerAccount.id != account.id,
    )):
        previous.is_deliverable = False
        previous.is_preferred = False
    # Flush the demotions before enabling the replacement identity so the
    # partial unique indexes cannot observe two deliverable accounts at once.
    session.flush()
    account.is_deliverable = True
    preferred_exists = session.scalar(select(CrmMessengerAccount.id).where(
        CrmMessengerAccount.user_id == token.user_id,
        CrmMessengerAccount.is_preferred.is_(True),
        CrmMessengerAccount.id != account.id,
    ))
    if preferred_exists is None:
        account.is_preferred = True
    contact.user_id = token.user_id
    token.consumed_at = now
    if onboarding is not None:
        onboarding.status = "claimed"
        onboarding.claimed_platform = "telegram"
        onboarding.claimed_at = now
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
    if token.purpose == "named_delivery":
        intent = token.intent_payload or {}
        kind = str(intent.get("notification_kind") or "")
        content_code = str(intent.get("content_code") or "")
        if kind and content_code:
            key = f"messenger-link:{token.id}:named-delivery"
            if not session.scalar(select(MasterclassNotification.id).where(
                MasterclassNotification.deduplication_key == key
            )):
                session.add(MasterclassNotification(
                    user_id=token.user_id,
                    notification_kind=kind,
                    content_code=content_code,
                    deduplication_key=key,
                    due_at=now,
                    payload={
                        "target_platform": "telegram",
                        "target_messenger_account_id": str(account.id),
                        "target_platform_user_id": account.platform_user_id,
                    },
                ))
        return True, (
            "<b>Telegram подключён.</b>\n\n"
            "Ссылка на приложение поставлена в отправку сюда и придёт отдельным сообщением."
        )
    if token.purpose == "account_credentials":
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
            credential = AccountCredential(
                user_id=token.user_id,
                password_hash=password_hash(raw_password, app_auth_secret),
                password_ciphertext=encrypt_password(raw_password, app_auth_secret),
                password_version=1,
                issued_via="telegram",
            )
            session.add(credential)
        if raw_password:
            return True, (
                "<b>Добро пожаловать! Доступ в личный кабинет готов.</b>\n\n"
                f"Логин: <code>{html.escape(email)}</code>\n"
                f"Пароль: <code>{raw_password}</code>\n\n"
                f'<a href="{html.escape(account_url, quote=True)}">Открыть личный кабинет</a>\n\n'
                "После первого входа сайт запомнит вас на этом устройстве."
            )
        return True, (
            "<b>Покупка добавлена в ваш личный кабинет.</b>\n\n"
            f"Логин: <code>{html.escape(email)}</code>\n"
            f'<a href="{html.escape(account_url, quote=True)}">Открыть личный кабинет</a>\n\n'
            + _existing_password_hint(credential)
        )
    return True, (
        "<b>Telegram подключён к личному кабинету.</b>\n\n"
        "Теперь сюда можно отправлять анкеты, материалы и уведомления Мастер-класса. "
        "Вернитесь в кабинет — шаг обновится автоматически.\n\n"
        f'<a href="{html.escape(account_url, quote=True)}?course_day=1&amp;course_material=day-01-messenger-link">Вернуться в Мастер-класс</a>'
    )
