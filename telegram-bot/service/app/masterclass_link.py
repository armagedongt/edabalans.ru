from __future__ import annotations

import hashlib
import html
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.customer_lifecycle import stop_presale_runs_for_user
from app.account_credentials import generate_password, password_hash
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


def _queue_link_messages(session: Session, user_id: str, token_id: str) -> None:
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
                    payload={"messenger_link_token_id": token_id},
                )
            )


def _queue_account_questionnaire(session: Session, user_id: str, token_id: str) -> None:
    key = f"account-onboarding:{token_id}:questionnaire"
    if session.scalar(
        select(MasterclassNotification.id).where(
            MasterclassNotification.user_id == user_id,
            MasterclassNotification.deduplication_key == key,
        )
    ):
        return
    session.add(
        MasterclassNotification(
            user_id=user_id,
            notification_kind="messenger_questionnaire",
            content_code="tpl_postpurchase_questionnaire",
            deduplication_key=key,
            due_at=datetime.now(UTC) + timedelta(seconds=1),
            payload={"messenger_link_token_id": token_id, "source": "account_onboarding"},
        )
    )


def consume_masterclass_link(
    session: Session,
    contact: Contact,
    telegram: dict,
    payload: str,
    app_auth_secret: str = "",
    account_url: str = "https://go.похудение-это-есть.рф/lk",
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
    if not token or token.platform != "telegram" or token.purpose not in {"link_account", "account_credentials"}:
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
        return True, "Данные для входа уже выданы в выбранном мессенджере. Если вы их потеряли, напишите Сергею."

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
    account.source = "account_onboarding" if token.purpose == "account_credentials" else "masterclass_link"
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
                password_version=1,
                issued_via="telegram",
            )
            session.add(credential)
        _queue_account_questionnaire(session, token.user_id, token.id)
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
            "Пароль не менялся. Если вы его потеряли, напишите Сергею."
        )
    _queue_link_messages(session, token.user_id, token.id)
    return True, "Telegram привязан. Сейчас пришлю ваши данные и анкету, а затем коротко напишу, что сделать дальше."
