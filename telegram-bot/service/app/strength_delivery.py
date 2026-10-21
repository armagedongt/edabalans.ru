"""Manual plan delivery through the existing preferred identity and transports."""
from __future__ import annotations

import hashlib
import hmac
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.database import get_db
from app.delivery_registry import validate_body
from app.maintenance import maintenance_allows
from app.max import MaxClient
from app.messenger_resolver import preferred_destination
from app.models import ManualMessage, CrmMessengerAccount
from app.telegram import TelegramClient

router = APIRouter()


class PlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    user_id: UUID
    messages: list[Annotated[str, Field(min_length=1, max_length=3800)]] = Field(min_length=1, max_length=40)


def plan_sender(settings: Settings, platform: str):
    if platform == "max":
        if not settings.max_bot_token:
            raise HTTPException(503, "Отправка в основной MAX пока не настроена")
        sender = MaxClient(settings.max_bot_token, bot_username=settings.max_bot_username,
                           channel_url=settings.max_channel_url, contact_url=settings.max_contact_url)
        return sender.send_html
    if not settings.telegram_test_bot_token:
        raise HTTPException(503, "Отправка в основной Telegram пока не настроена")
    sender = TelegramClient(settings.telegram_test_bot_token, proxy_url=settings.telegram_proxy_url,
                            api_base_url=settings.telegram_api_base_url, gateway_token=settings.telegram_gateway_token,
                            channel_id=settings.telegram_channel_id)
    return sender.send_html_message


def deliver_saved_plan(session: Session, settings: Settings, body: PlanPayload) -> dict:
    destination = preferred_destination(session, str(body.user_id))
    primary = session.scalar(select(CrmMessengerAccount).where(
        CrmMessengerAccount.user_id == str(body.user_id), CrmMessengerAccount.is_preferred.is_(True)
    ))
    if destination is None or (primary is not None and primary.id != destination.account_id):
        raise HTTPException(409, "Основной мессенджер не подключён или недоступен. Проверьте привязку в личном кабинете.")
    if destination.platform == "telegram" and not maintenance_allows(
        settings.telegram_maintenance_mode, settings.telegram_maintenance_allowed_user_ids, destination.platform_user_id
    ):
        raise HTTPException(503, "Отправка в Telegram временно недоступна")
    send = plan_sender(settings, destination.platform)
    ids = [str(uuid5(NAMESPACE_URL, f"strength-plan:{body.user_id}:{body.request_id}:{index}")) for index in range(len(body.messages))]
    for receipt_id, message in zip(ids, body.messages):
        validate_body("strength_workout_plan", message)
        if len(message.encode("utf-16-le")) // 2 > 4096:
            raise HTTPException(422, "Часть плана слишком длинная")
        existing = session.get(ManualMessage, receipt_id)
        if existing and (existing.contact_id != destination.contact_id or existing.body_source != message):
            raise HTTPException(409, "Параметры отправки изменились. Начните новую отправку.")
        if existing and existing.status != "sent":
            raise HTTPException(409, "Предыдущая доставка не подтверждена. Проверьте мессенджер перед новой отправкой.")
    message_ids = []
    for receipt_id, message in zip(ids, body.messages):
        existing = session.get(ManualMessage, receipt_id)
        if existing:
            message_ids.append(existing.platform_message_id)
            continue
        receipt = ManualMessage(id=receipt_id, contact_id=destination.contact_id, direction="out",
                                body_source=message, status="sending")
        session.add(receipt)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "Эта отправка уже обрабатывается. Проверьте мессенджер.") from None
        try:
            message_id = send(destination.platform_user_id if destination.platform == "max" else destination.chat_id, message)
            if not message_id:
                raise ValueError("missing delivery confirmation")
        except Exception:
            receipt.status = "unconfirmed"
            session.commit()
            raise HTTPException(502, f"Доставка не подтверждена. Подтверждено частей: {len(message_ids)} из {len(ids)}. Проверьте мессенджер перед повторной отправкой.") from None
        receipt.status = "sent"
        receipt.platform_message_id = str(message_id)
        session.commit()
        message_ids.append(str(message_id))
    return {"ok": True, "platform": destination.platform, "message_ids": message_ids}


@router.post("/internal/strength-plan", include_in_schema=False)
async def receive_plan(request: Request, signature: str = Header(default="", alias="X-Edabalans-Strength-Signature"),
                       session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    raw = await request.body()
    if len(raw) > 650000:
        raise HTTPException(413, "План слишком большой")
    if not settings.app_auth_secret:
        raise HTTPException(503, "Сервис отправки не настроен")
    expected = hmac.new(settings.app_auth_secret.encode(), b"strength-plan\n" + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(403, "Недопустимая подпись запроса")
    try:
        body = PlanPayload.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(422, "Некорректные параметры плана") from None
    return await run_in_threadpool(deliver_saved_plan, session, settings, body)
