import asyncio
from types import SimpleNamespace

import pytest
from httpx import ReadTimeout

from app.operator_navigation import handle_update, navigation_loop
from app.telegram import TelegramError


def update(text="/links", user=11, chat=11, kind="private"):
    return {"update_id": 1, "message": {"from": {"id": user}, "chat": {"id": chat, "type": kind}, "text": text}}


class Sender:
    def __init__(self, pin_fails=False):
        self.calls = []
        self.pin_fails = pin_fails

    def call(self, method, payload, **kwargs):
        self.calls.append((method, payload))
        if method == "pinChatMessage" and self.pin_fails:
            raise TelegramError("pin denied")
        return {"message_id": 72}


@pytest.mark.parametrize("role,path", [("technical", "/admin"), ("finance", "/crm"), ("marketing", "/admin/marketing")])
def test_owner_gets_role_card_and_new_pin(role, path):
    sender = Sender()
    assert handle_update(sender, role, {"11"}, update())
    method, payload = sender.calls[0]
    assert method == "sendMessage" and payload["chat_id"] == "11"
    urls = [b["url"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]
    assert any(url.endswith(path) for url in urls)
    assert sender.calls[1] == ("pinChatMessage", {"chat_id": "11", "message_id": 72, "disable_notification": True})


@pytest.mark.parametrize("message", [update(user=12), update(chat=-1, kind="group"), update(chat=12), update("idea"), update("/unknown"), {}])
def test_other_people_chats_and_text_do_not_trigger_navigation(message):
    sender = Sender()
    assert not handle_update(sender, "technical", {"11"}, message)
    assert sender.calls == []


def test_pin_failure_does_not_retry_already_delivered_card():
    assert handle_update(Sender(pin_fails=True), "technical", {"11"}, update())


@pytest.mark.parametrize("failed_method", ["pinChatMessage", "setMyCommands"])
def test_network_error_after_delivery_does_not_resend_card(failed_method):
    class NetworkSender(Sender):
        def call(self, method, payload, **kwargs):
            if method == failed_method:
                raise ReadTimeout("network timeout")
            return super().call(method, payload, **kwargs)

    sender = NetworkSender()
    assert handle_update(sender, "technical", {"11"}, update())
    assert sum(method == "sendMessage" for method, _ in sender.calls) == 1


@pytest.mark.parametrize("first_blocked", [False, True])
def test_polling_acknowledges_updates_and_unblocks_second_owner(monkeypatch, first_blocked):
    import app.operator_navigation as nav
    offsets, sent, menus = [], [], []

    class PollSender:
        def __init__(self, *args, **kwargs):
            pass

        def call(self, method, payload, **kwargs):
            if method == "getWebhookInfo":
                return {"url": ""}
            if method == "setMyCommands":
                menus.append(payload["scope"]["chat_id"])
            if method == "getUpdates":
                offsets.append(payload["offset"])
                if payload["offset"] == 3:
                    raise asyncio.CancelledError
                if len(offsets) > 4:
                    raise asyncio.CancelledError
                second = update("/start", user=12, chat=12)
                second["update_id"] = 2
                return [update(), second]
            if method == "sendMessage":
                if first_blocked and payload["chat_id"] == "11":
                    raise TelegramError("Telegram API HTTP 403")
                sent.append(payload["chat_id"])
                return {"message_id": 72}
            return True

    async def no_wait(*args):
        pass

    monkeypatch.setattr(nav, "TelegramClient", PollSender)
    monkeypatch.setattr(nav.asyncio, "sleep", no_wait)
    settings = SimpleNamespace(technical_telegram_bot_token="test", technical_telegram_recipient_ids="11,12", telegram_proxy_url="", telegram_api_base_url="", telegram_gateway_token="")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(navigation_loop(settings, "technical"))
    assert offsets == ([None, None, None, 3] if first_blocked else [None, 3])
    assert sent == (["12"] if first_blocked else ["11", "12"])
    assert menus.count("12") == 2  # startup plus the owner's later /start


def test_unstarted_second_recipient_does_not_block_polling(monkeypatch):
    import app.operator_navigation as nav
    calls = []

    class PollSender:
        def __init__(self, *args, **kwargs):
            pass

        def call(self, method, payload, **kwargs):
            calls.append((method, payload))
            if method == "getWebhookInfo":
                return {"url": ""}
            if method == "setMyCommands" and payload["scope"]["chat_id"] == "12":
                raise TelegramError("chat not found")
            if method == "getUpdates":
                raise asyncio.CancelledError
            return True

    monkeypatch.setattr(nav, "TelegramClient", PollSender)
    settings = SimpleNamespace(technical_telegram_bot_token="test", technical_telegram_recipient_ids="11,12", telegram_proxy_url="", telegram_api_base_url="", telegram_gateway_token="")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(navigation_loop(settings, "technical"))
    assert calls[-1][0] == "getUpdates"
