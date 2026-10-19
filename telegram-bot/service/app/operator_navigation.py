"""Private navigation commands for the owner's three notification bots."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from httpx import HTTPError

from app.telegram import TelegramClient, TelegramError

logger = logging.getLogger(__name__)
CARDS = json.loads(Path(__file__).with_name("operator_navigation.json").read_text(encoding="utf-8"))


def configure_commands(sender: TelegramClient, owner: str) -> None:
    sender.call("setMyCommands", {
        "scope": {"type": "chat", "chat_id": owner},
        "commands": [{"command": "links", "description": "Быстрый доступ — вернуть закреп"}],
    })


def handle_update(sender: TelegramClient, role: str, owners: set[str], update: dict) -> bool:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    user_id = str((message.get("from") or {}).get("id", ""))
    if chat.get("type") != "private" or str(chat.get("id", "")) != user_id or user_id not in owners:
        return False
    text = message.get("text") or ""
    command = text.split(maxsplit=1)[0].split("@", 1)[0] if text else ""
    if command not in {"/links", "/start", "/help"}:
        return False
    card = CARDS[role]
    sent = sender.call("sendMessage", {"chat_id": user_id, **card})
    try:
        sender.call("pinChatMessage", {"chat_id": user_id, "message_id": sent["message_id"], "disable_notification": True})
    except (TelegramError, HTTPError):
        logger.error("Operator navigation %s delivered but pin failed", role)
    try:
        configure_commands(sender, user_id)
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
                        await asyncio.to_thread(configure_commands, sender, owner)
                    except TelegramError:
                        logger.error("Operator navigation %s command menu unavailable for a recipient", role)
                registered = True
            updates = await asyncio.to_thread(sender.call, "getUpdates", {
                "offset": offset, "timeout": 25, "allowed_updates": ["message"],
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
