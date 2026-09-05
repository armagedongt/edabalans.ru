from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.account_security import token_hash
from app.config import Settings
from app.database import SessionLocal
from app.models import AccountOnboarding, MessengerLinkToken, Payment, UserEmail


logger = logging.getLogger(__name__)
CLAIM_TTL = timedelta(hours=24)
MAX_EMAIL_ATTEMPTS = 8


def _fernet(settings: Settings) -> Fernet:
    if not settings.app_auth_secret:
        raise RuntimeError("APP_AUTH_SECRET is required")
    digest = hashlib.sha256(settings.app_auth_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_bundle(bundle: dict, settings: Settings) -> str:
    return _fernet(settings).encrypt(
        json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def _decrypt_bundle(value: str, settings: Settings) -> dict:
    try:
        return json.loads(_fernet(settings).decrypt(value.encode("ascii")).decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("account onboarding payload is invalid") from exc


def _claim_token() -> str:
    return "M" + secrets.token_urlsafe(31)


def ensure_paid_account_onboarding(
    db: Session,
    payment: Payment,
    settings: Settings,
) -> AccountOnboarding | None:
    if payment.payment_status != "paid" or payment.user_id is None:
        return None
    existing = db.scalar(
        select(AccountOnboarding).where(AccountOnboarding.payment_id == payment.id)
    )
    if existing is not None:
        return existing

    now = datetime.now(UTC)
    expires_at = now + CLAIM_TTL
    tokens = {"telegram": _claim_token(), "max": _claim_token()}
    bundle = {
        "telegram": tokens["telegram"],
        "max": tokens["max"],
        "payment_id": str(payment.id),
    }
    row = AccountOnboarding(
        user_id=payment.user_id,
        payment_id=payment.id,
        claim_bundle_encrypted=_encrypt_bundle(bundle, settings),
        expires_at=expires_at,
        next_email_attempt_at=now,
    )
    db.add(row)
    db.flush()
    for platform, raw_token in tokens.items():
        db.add(
            MessengerLinkToken(
                user_id=payment.user_id,
                account_onboarding_id=row.id,
                platform=platform,
                purpose="account_credentials",
                token_hash=token_hash(raw_token),
                expires_at=expires_at,
            )
        )
    return row


def onboarding_links(row: AccountOnboarding, settings: Settings) -> dict[str, str]:
    bundle = _decrypt_bundle(row.claim_bundle_encrypted, settings)
    telegram_username = settings.account_telegram_bot_username.strip().lstrip("@")
    max_username = settings.account_max_bot_username.strip().lstrip("@")
    return {
        "telegram": (
            f"https://t.me/{telegram_username}?start={bundle['telegram']}"
            if telegram_username
            else ""
        ),
        "max": (
            f"https://max.ru/{max_username}?start={bundle['max']}"
            if max_username
            else ""
        ),
    }


def account_access_email(
    *, email: str, links: dict[str, str], expires_at: datetime, settings: Settings
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Доступ в личный кабинет"
    sender = settings.smtp_from_email
    message["From"] = f"{settings.smtp_from_name} <{sender}>" if settings.smtp_from_name else sender
    message["To"] = email
    if settings.smtp_reply_to:
        message["Reply-To"] = settings.smtp_reply_to
    lines = [
        "Оплата прошла. Доступ к материалам уже добавлен.",
        "",
        "Чтобы получить логин и пароль от личного кабинета, откройте удобный мессенджер:",
    ]
    if links.get("telegram"):
        lines.append(f"Telegram: {links['telegram']}")
    if links.get("max"):
        lines.append(f"MAX: {links['max']}")
    lines.extend(
        (
            "",
            f"Ссылки действуют до {expires_at.astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M')} (МСК).",
            "После первой авторизации сайт запомнит вас на этом устройстве.",
            "",
            "Если ссылка перестала действовать или что-то не получилось, ответьте на это письмо.",
        )
    )
    message.set_content("\n".join(lines))
    buttons = "".join(
        f'<p><a href="{url}" style="display:inline-block;padding:13px 22px;border-radius:12px;background:{"#229ED9" if platform == "telegram" else "#2563eb"};color:#fff;text-decoration:none;font-weight:700">{"Telegram" if platform == "telegram" else "MAX"}</a></p>'
        for platform, url in links.items()
        if url
    )
    message.add_alternative(
        f"""<!doctype html><html><body style="font:16px/1.55 Arial,sans-serif;color:#17172b">
        <div style="max-width:620px;margin:auto;padding:28px 20px">
        <h1 style="font-size:28px">Доступ в личный кабинет</h1>
        <p>Оплата прошла. Доступ к материалам уже добавлен.</p>
        <p>Чтобы получить логин и пароль, откройте удобный мессенджер:</p>
        {buttons}
        <p>Ссылки действуют 24 часа. После первой авторизации сайт запомнит вас на этом устройстве.</p>
        <p>Если ссылка перестала действовать или что-то не получилось, ответьте на это письмо.</p>
        </div></body></html>""",
        subtype="html",
    )
    return message


def _send_message(message: EmailMessage, settings: Settings) -> None:
    context = ssl.create_default_context()
    if settings.smtp_use_ssl:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=20, context=context
        )
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
    with smtp:
        if not settings.smtp_use_ssl and settings.smtp_starttls:
            smtp.starttls(context=context)
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def process_due_account_email(settings: Settings) -> bool:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        row = db.scalar(
            select(AccountOnboarding)
            .where(
                AccountOnboarding.email_status.in_(("pending", "retry")),
                or_(
                    AccountOnboarding.next_email_attempt_at.is_(None),
                    AccountOnboarding.next_email_attempt_at <= now,
                ),
            )
            .order_by(AccountOnboarding.created_at)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return False
        email = db.scalar(
            select(UserEmail.email_normalized)
            .where(UserEmail.user_id == row.user_id)
            .order_by(UserEmail.is_primary.desc(), UserEmail.created_at)
            .limit(1)
        )
        if not email:
            row.email_status = "failed"
            row.email_error = "user email is missing"
            db.commit()
            return True
        try:
            message = account_access_email(
                email=email,
                links=onboarding_links(row, settings),
                expires_at=row.expires_at,
                settings=settings,
            )
            _send_message(message, settings)
            row.email_status = "sent"
            row.email_sent_at = now
            row.email_error = None
        except Exception as exc:  # SMTP/network errors are retried from durable DB state.
            row.email_attempt_count += 1
            row.email_error = str(exc)[:2000]
            if row.email_attempt_count >= MAX_EMAIL_ATTEMPTS:
                row.email_status = "failed"
            else:
                row.email_status = "retry"
                delay_minutes = min(60, 2 ** min(row.email_attempt_count, 6))
                row.next_email_attempt_at = now + timedelta(minutes=delay_minutes)
            logger.exception("Account access email delivery failed")
        db.commit()
        return True


async def account_email_worker(settings: Settings, stop: asyncio.Event) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        logger.warning("Account email worker is idle: SMTP is not configured")
        return
    while not stop.is_set():
        processed = await asyncio.to_thread(process_due_account_email, settings)
        if processed:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.account_email_poll_seconds)
        except TimeoutError:
            pass
