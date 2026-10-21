"""Private navigation commands for the owner's three notification bots."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from pathlib import Path

from httpx import HTTPError
from sqlalchemy import JSON, DateTime, Numeric, String, column, func, select, table

from app.database import SessionLocal
from app.telegram import TelegramClient, TelegramError

logger = logging.getLogger(__name__)
CARDS = json.loads(Path(__file__).with_name("operator_navigation.json").read_text(encoding="utf-8"))


def configure_commands(sender: TelegramClient, owner: str, role: str = "technical") -> None:
    commands = [{"command": "links", "description": "Быстрые ссылки"}]
    if role == "finance":
        commands += [{"command": "payments", "description": "Последние 10 успешных оплат"},
                     {"command": "failed", "description": "Последние 10 неуспешных оплат"}]
    sender.call("setMyCommands", {
        "scope": {"type": "chat", "chat_id": owner},
        "commands": commands,
    })


def payment_summary(failed: bool) -> str:
    # Read the existing commerce ledger; never copy customer identities into chat summaries.
    p = table("payments", column("id"), column("product_name_raw", String),
              column("amount", Numeric), column("currency", String), column("payment_status", String),
              column("paid_at", DateTime(timezone=True)), column("source_event_at", DateTime(timezone=True)),
              column("created_at", DateTime(timezone=True)), column("raw_payload", JSON))
    c = table("offer_checkouts", column("payment_id"), column("checkout_kind", String))
    event_at = func.coalesce(p.c.paid_at, p.c.source_event_at, p.c.created_at)
    metadata = p.c.raw_payload
    stmt = (select(event_at.label("event_at"), p.c.amount, p.c.currency, p.c.product_name_raw)
            .select_from(p.outerjoin(c, c.c.payment_id == p.c.id))
            .where(p.c.payment_status.in_(("failed", "cancelled") if failed else ("paid", "confirmed")),
                   func.coalesce(c.c.checkout_kind, "") != "robokassa_live_probe",
                   func.coalesce(metadata["test_mode"].as_boolean(), False).is_(False),
                   func.coalesce(metadata["integration"]["test_mode"].as_boolean(), False).is_(False),
                   func.coalesce(metadata["integration"]["live_probe"].as_boolean(), False).is_(False))
            .order_by(event_at.desc(), p.c.id.desc()).limit(10))
    with SessionLocal() as db:
        rows = db.execute(stmt).all()
    heading = "Неуспешные оплаты" if failed else "Последние успешные оплаты"
    lines = [f"<b>{heading}</b> · до 10 операций", "Время московское", ""]
    for at, amount, currency, product in rows:
        if isinstance(at, str):
            at = datetime.fromisoformat(at)
        stamp = at.replace(tzinfo=at.tzinfo or timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
        value = f"{Decimal(amount):,.2f}".replace(",", " ").removesuffix(".00") if amount is not None else "—"
        label = " ".join(str(product or "Покупка").split())[:160]
        unit = "₽" if currency in {None, "", "RUB"} else escape(currency)
        lines.append(f"{stamp} · {value} {unit} · {escape(label)}")
    if not rows:
        lines.append("Операций пока нет.")
    return "\n".join(lines)


def handle_update(sender: TelegramClient, role: str, owners: set[str], update: dict) -> bool:
    callback = update.get("callback_query") or {}
    message = callback.get("message") or update.get("message") or {}
    chat = message.get("chat") or {}
    user_id = str(((callback if callback else message).get("from") or {}).get("id", ""))
    if chat.get("type") != "private" or str(chat.get("id", "")) != user_id or user_id not in owners:
        return False
    text = ({"owner:payments": "/payments", "owner:failed": "/failed"}.get(callback.get("data"), "")
            if callback else message.get("text") or "")
    command = text.split(maxsplit=1)[0].split("@", 1)[0] if text else ""
    if role == "finance" and command in {"/payments", "/failed"}:
        if callback:
            sender.call("answerCallbackQuery", {"callback_query_id": callback["id"]})
        try:
            body = payment_summary(command == "/failed")
        except Exception:
            logger.error("Owner payment summary unavailable")
            body = "Не удалось прочитать оплаты. Попробуйте ещё раз чуть позже."
        sender.call("sendMessage", {"chat_id": user_id, "text": body, "parse_mode": "HTML"})
        return True
    if command not in {"/links", "/start", "/help"}:
        return False
    card = CARDS[role]
    sender.call("sendMessage", {"chat_id": user_id, **card})
    try:
        configure_commands(sender, user_id, role)
    except (TelegramError, HTTPError):
        logger.error("Operator navigation %s command menu unavailable for a recipient", role)
    return True


async def navigation_loop(settings, role: str) -> None:
    token = getattr(settings, f"{role}_telegram_bot_token")
    owners = {value.strip() for value in getattr(settings, f"{role}_telegram_recipient_ids").split(",") if value.strip()}
    sender = TelegramClient(token, proxy_url=settings.telegram_proxy_url,
                            api_base_url=settings.telegram_api_base_url, gateway_token=settings.telegram_gateway_token)
    offset = None
    registered = False
    attempts: dict[int, int] = {}
    while True:
        try:
            if not registered:
                info = await asyncio.to_thread(sender.call, "getWebhookInfo", {})
                if info.get("url"):
                    logger.error("Operator navigation %s has an existing webhook; polling not started", role)
                    return
                for owner in sorted(owners):
                    try:
                        await asyncio.to_thread(configure_commands, sender, owner, role)
                    except TelegramError:
                        logger.error("Operator navigation %s command menu unavailable for a recipient", role)
                registered = True
            updates = await asyncio.to_thread(sender.call, "getUpdates", {
                "offset": offset, "timeout": 25, "allowed_updates": ["message", "callback_query"],
            }, timeout=35)
            for update in updates:
                update_id = int(update["update_id"])
                try:
                    await asyncio.to_thread(handle_update, sender, role, owners, update)
                except Exception:
                    attempts[update_id] = attempts.get(update_id, 0) + 1
                    if attempts[update_id] < 3:
                        raise
                    logger.error("Operator navigation %s update failed after three attempts; skipping", role)
                attempts.pop(update_id, None)
                offset = update_id + 1
        except asyncio.CancelledError:
            raise
        except Exception:
            # Exception strings can include transport URLs with credentials.
            logger.error("Operator navigation %s failed; retrying", role)
            await asyncio.sleep(5)
