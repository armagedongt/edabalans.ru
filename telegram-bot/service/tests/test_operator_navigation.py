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
def test_owner_gets_role_links_without_repinning(role, path):
    sender = Sender()
    assert handle_update(sender, role, {"11"}, update())
    method, payload = sender.calls[0]
    assert method == "sendMessage" and payload["chat_id"] == "11"
    assert path in payload["text"] and payload["parse_mode"] == "HTML"
    assert all(method != "pinChatMessage" for method, _ in sender.calls)
    commands = sender.calls[1][1]["commands"]
    assert {c["command"] for c in commands} == ({"links", "payments", "failed"} if role == "finance" else {"links"})


@pytest.mark.parametrize("message", [update(user=12), update(chat=-1, kind="group"), update(chat=12), update("idea"), update("/unknown"), {}])
def test_other_people_chats_and_text_do_not_trigger_navigation(message):
    sender = Sender()
    assert not handle_update(sender, "technical", {"11"}, message)
    assert sender.calls == []


@pytest.mark.parametrize("failed_method", ["setMyCommands"])
def test_network_error_after_delivery_does_not_resend_card(failed_method):
    class NetworkSender(Sender):
        def call(self, method, payload, **kwargs):
            if method == failed_method:
                raise ReadTimeout("network timeout")
            return super().call(method, payload, **kwargs)

    sender = NetworkSender()
    assert handle_update(sender, "technical", {"11"}, update())
    assert sum(method == "sendMessage" for method, _ in sender.calls) == 1


def callback(user=11, chat=11, data="owner:payments"):
    return {"callback_query": {"id": "cb", "from": {"id": user}, "data": data,
                               "message": {"chat": {"id": chat, "type": "private"}}}}


@pytest.mark.parametrize("message", [update("/payments", user=12), callback(user=12), callback(chat=12), callback(data="unknown")])
def test_payment_reports_are_private_and_owner_only(monkeypatch, message):
    import app.operator_navigation as nav
    monkeypatch.setattr(nav, "payment_summary", lambda *_: pytest.fail("Must not read payments"))
    sender = Sender()
    assert not handle_update(sender, "finance", {"11"}, message)
    assert sender.calls == []


def test_finance_buttons_and_commands_deliver_report_without_pin(monkeypatch):
    import app.operator_navigation as nav
    requested = []
    def report(failed):
        requested.append(failed)
        return "report"
    monkeypatch.setattr(nav, "payment_summary", report)
    sender = Sender()
    assert handle_update(sender, "finance", {"11"}, callback())
    assert handle_update(sender, "finance", {"11"}, update("/failed"))
    assert requested == [False, True]
    assert [method for method, _ in sender.calls] == ["answerCallbackQuery", "sendMessage", "sendMessage"]
    assert not handle_update(sender, "marketing", {"11"}, callback())


def test_payment_database_error_is_safe_and_does_not_lose_the_request(monkeypatch):
    import app.operator_navigation as nav
    def unavailable(_):
        raise RuntimeError("secret connection details")
    monkeypatch.setattr(nav, "payment_summary", unavailable)
    sender = Sender()
    assert handle_update(sender, "finance", {"11"}, update("/payments"))
    assert "Попробуйте" in sender.calls[0][1]["text"]
    assert "secret" not in str(sender.calls)


def test_payment_summary_filters_limits_orders_and_omits_customer_data(monkeypatch):
    import app.operator_navigation as nav
    from datetime import datetime, timedelta
    from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, Numeric, String, Table, create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite://")
    metadata = MetaData()
    payments = Table("payments", metadata, Column("id", Integer, primary_key=True),
                     Column("product_name_raw", String), Column("amount", Numeric), Column("currency", String),
                     Column("payment_status", String), Column("paid_at", DateTime), Column("source_event_at", DateTime),
                     Column("created_at", DateTime), Column("raw_payload", JSON), Column("email_at_purchase", String))
    checkouts = Table("offer_checkouts", metadata, Column("payment_id", Integer), Column("checkout_kind", String))
    metadata.create_all(engine)
    base = datetime(2026, 10, 1, 10)
    rows = [dict(id=i, product_name_raw=f"Курс {i}", amount=i*100, currency="RUB", payment_status="paid",
                 created_at=base+timedelta(days=i), paid_at=None, source_event_at=None,
                 raw_payload={}, email_at_purchase="private@example.test") for i in range(1, 19)]
    # A recently imported old payment must not displace a recent real operation.
    rows[0].update(created_at=base+timedelta(days=100), paid_at=base+timedelta(days=1))
    rows[11].update(paid_at=base+timedelta(days=20), source_event_at=base+timedelta(days=15))
    rows[10].update(source_event_at=base+timedelta(days=19))
    rows[11]["payment_status"] = "confirmed"
    rows[12]["payment_status"] = "pending"
    rows[13]["payment_status"] = "failed"
    rows[14]["payment_status"] = "cancelled"
    rows[15]["raw_payload"] = {"integration": {"test_mode": True}}
    rows[16]["raw_payload"] = {"test_mode": True}
    with engine.begin() as db:
        db.execute(payments.insert(), rows)
        db.execute(checkouts.insert(), {"payment_id": 18, "checkout_kind": "robokassa_live_probe"})
    monkeypatch.setattr(nav, "SessionLocal", sessionmaker(bind=engine))
    body = nav.payment_summary(False)
    assert len([line for line in body.splitlines() if "₽ ·" in line]) == 10
    assert body.index("Курс 12") < body.index("Курс 11")
    assert "21.10.2026 13:00" in body and "20.10.2026 13:00" in body
    assert "Курс 1\n" not in body and "Курс 2\n" not in body
    assert "13:00" in body and "private@" not in body
    assert all(f"Курс {i}" not in body for i in range(13, 19))
    failed = nav.payment_summary(True)
    assert "Курс 14" in failed and "Курс 15" in failed and "Курс 13" not in failed
    with engine.begin() as db:
        db.execute(payments.delete())
    assert "Операций пока нет" in nav.payment_summary(False)


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
