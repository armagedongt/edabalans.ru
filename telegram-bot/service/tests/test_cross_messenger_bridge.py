from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.main as main_module
from app.cross_messenger_bridge import (
    mapped_max_message,
    mapped_telegram_message,
    max_pair,
    mirror_text,
    process_max_update,
    process_telegram_update,
    is_telegram_pair_update,
    telegram_pair,
)
from app.database import Base, get_db
from app.main import app
from app.models import MessagingBridgeDelivery, MessagingBridgeMessage, MessagingBridgePair


def make_session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


class FakeMaxSender:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.deleted = []
        self.fail_sends = 0

    def send_chat_html(self, chat_id, text, reply_to_message_id=None):
        if self.fail_sends:
            self.fail_sends -= 1
            raise RuntimeError("temporary MAX failure")
        self.sent.append((chat_id, text, reply_to_message_id))
        return f"max-{len(self.sent)}"

    def edit_chat_html(self, message_id, text):
        self.edited.append((message_id, text))

    def delete_message(self, message_id):
        self.deleted.append(message_id)


class FakeTelegramSender:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.deleted = []
        self.fail_sends = 0

    def send_html_message(self, chat_id, text, reply_to_message_id=None):
        if self.fail_sends:
            self.fail_sends -= 1
            raise RuntimeError("temporary Telegram failure")
        self.sent.append((chat_id, text, reply_to_message_id))
        return str(700 + len(self.sent))

    def edit_html_message(self, chat_id, message_id, text):
        self.edited.append((chat_id, message_id, text))

    def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


def test_mirror_text_marks_source_without_exposing_profile_data():
    assert mirror_text("telegram", "Вика <admin>", "Тарелка <готова>") == (
        "<b>Из Telegram · Вика &lt;admin&gt;</b>\nТарелка &lt;готова&gt;"
    )


def test_pair_lookup_uses_only_enabled_chat_pairs():
    with make_session() as session:
        active = MessagingBridgePair(
            key="sprint-test",
            status="active",
            telegram_channel_id="-10001",
            max_channel_id="101",
            telegram_practice_chat_id="-10002",
            max_practice_chat_id="102",
        )
        paused = MessagingBridgePair(
            key="paused",
            status="paused",
            telegram_channel_id="-10003",
            max_channel_id="103",
            telegram_practice_chat_id="-10004",
            max_practice_chat_id="104",
        )
        session.add_all((active, paused))
        session.commit()

        assert telegram_pair(session, "-10002").id == active.id
        assert max_pair(session, "101").id == active.id
        assert telegram_pair(session, "-10004") is None
        assert max_pair(session, "103") is None


def test_unauthenticated_telegram_webhook_can_never_trigger_a_paired_delivery():
    with make_session() as session:
        session.add(
            MessagingBridgePair(
                key="untrusted",
                status="active",
                telegram_channel_id="-10001",
                max_channel_id="101",
                telegram_practice_chat_id="-10002",
                max_practice_chat_id="102",
            )
        )
        session.commit()
        update = {
            "update_id": 99,
            "channel_post": {"message_id": 1, "chat": {"id": -10001}, "text": "Подделка"},
        }
        assert is_telegram_pair_update(session, update) is True
        assert main_module.process_update(update, session, telegram_source_trusted=False) == {
            "ok": True,
            "bridge": "unauthenticated",
        }


def test_message_mapping_finds_parent_by_each_platform_id():
    with make_session() as session:
        pair = MessagingBridgePair(
            key="main",
            status="test",
            telegram_channel_id="-10001",
            max_channel_id="101",
            telegram_practice_chat_id="-10002",
            max_practice_chat_id="102",
        )
        session.add(pair)
        session.flush()
        message = MessagingBridgeMessage(
            pair_id=pair.id,
            kind="practice",
            telegram_message_id="22",
            max_message_id="max-22",
            source_platform="telegram",
            source_author_name="Вика",
        )
        session.add(message)
        session.commit()

        assert mapped_telegram_message(session, pair.id, "22").id == message.id
        assert mapped_max_message(session, pair.id, "max-22").id == message.id


def test_telegram_practice_message_is_mirrored_once_with_its_reply_parent():
    with make_session() as session:
        pair = MessagingBridgePair(
            key="sprint-test",
            status="test",
            telegram_channel_id="-10001",
            max_channel_id="101",
            telegram_practice_chat_id="-10002",
            max_practice_chat_id="102",
        )
        session.add(pair)
        session.flush()
        session.add(
            MessagingBridgeMessage(
                pair_id=pair.id,
                kind="practice",
                telegram_message_id="10",
                max_message_id="max-parent",
                source_platform="telegram",
                source_author_name="Вика",
            )
        )
        session.commit()
        sender = FakeMaxSender()
        update = {
            "update_id": 101,
            "message": {
                "message_id": 11,
                "chat": {"id": -10002},
                "from": {"first_name": "Виктория"},
                "text": "Я попробовала так",
                "reply_to_message": {"message_id": 10},
            },
        }

        assert process_telegram_update(session, update, sender)["bridge"] == "mirrored"
        assert sender.sent == [
            ("102", "<b>Из Telegram · Виктория</b>\nЯ попробовала так", "max-parent")
        ]
        assert process_telegram_update(session, update, sender)["bridge"] == "duplicate"
        assert len(sender.sent) == 1
        delivery = session.scalar(select(MessagingBridgeDelivery))
        assert delivery.status == "delivered"


def test_telegram_channel_post_keeps_author_text_without_chat_label():
    with make_session() as session:
        pair = MessagingBridgePair(
            key="sprint-channel",
            status="active",
            telegram_channel_id="-10001",
            max_channel_id="101",
            telegram_practice_chat_id="-10002",
            max_practice_chat_id="102",
        )
        session.add(pair)
        session.commit()
        sender = FakeMaxSender()

        result = process_telegram_update(
            session,
            {
                "update_id": 102,
                "channel_post": {
                    "message_id": 20,
                    "chat": {"id": -10001},
                    "text": "Практика дня",
                },
            },
            sender,
        )

        assert result["target"] == "max"
        assert sender.sent == [("101", "Практика дня", None)]


def test_telegram_redelivery_retries_a_persisted_failed_delivery_without_second_mapping():
    with make_session() as session:
        session.add(
            MessagingBridgePair(
                key="retry",
                status="active",
                telegram_channel_id="-10001",
                max_channel_id="101",
                telegram_practice_chat_id="-10002",
                max_practice_chat_id="102",
            )
        )
        session.commit()
        sender = FakeMaxSender()
        sender.fail_sends = 1
        update = {
            "update_id": 103,
            "channel_post": {"message_id": 21, "chat": {"id": -10001}, "text": "Не терять"},
        }

        try:
            process_telegram_update(session, update, sender)
        except RuntimeError as exc:
            assert "temporary MAX failure" in str(exc)
        else:
            raise AssertionError("outbound failure must reach the webhook caller")

        assert process_telegram_update(session, update, sender) == {
            "ok": True,
            "bridge": "retried",
            "target": "max",
        }
        assert sender.sent == [("101", "Не терять", None)]
        assert session.scalar(select(MessagingBridgeDelivery)).attempts == 2


def test_max_practice_message_is_mirrored_to_telegram_with_reply_parent():
    with make_session() as session:
        pair = MessagingBridgePair(
            key="sprint-max",
            status="active",
            telegram_channel_id="-10001",
            max_channel_id="101",
            telegram_practice_chat_id="-10002",
            max_practice_chat_id="102",
        )
        session.add(pair)
        session.flush()
        session.add(
            MessagingBridgeMessage(
                pair_id=pair.id,
                kind="practice",
                telegram_message_id="20",
                max_message_id="max-parent",
                source_platform="max",
                source_author_name="Павел",
            )
        )
        session.commit()
        sender = FakeTelegramSender()
        update = {
            "update_type": "message_created",
            "timestamp": 1,
            "message": {
                "recipient": {"chat_id": "102"},
                "sender": {"name": "Павел"},
                "body": {"mid": "max-21", "text": "У меня получилось"},
                "link": {"type": "reply", "mid": "max-parent"},
            },
        }

        assert process_max_update(session, update, sender)["bridge"] == "mirrored"
        assert sender.sent == [
            ("-10002", "<b>Из MAX · Павел</b>\nУ меня получилось", "20")
        ]
        assert process_max_update(session, update, sender)["bridge"] == "duplicate"
        assert len(sender.sent) == 1


def test_max_redelivery_retries_a_persisted_failed_telegram_delivery():
    with make_session() as session:
        session.add(
            MessagingBridgePair(
                key="max-retry",
                status="active",
                telegram_channel_id="-10001",
                max_channel_id="101",
                telegram_practice_chat_id="-10002",
                max_practice_chat_id="102",
            )
        )
        session.commit()
        sender = FakeTelegramSender()
        sender.fail_sends = 1
        update = {
            "update_type": "message_created",
            "timestamp": 1,
            "message": {
                "recipient": {"chat_id": "102"},
                "sender": {"name": "Павел"},
                "body": {"mid": "max-retry-1", "text": "Не терять"},
            },
        }

        try:
            process_max_update(session, update, sender)
        except RuntimeError as exc:
            assert "temporary Telegram failure" in str(exc)
        else:
            raise AssertionError("outbound failure must reach the webhook caller")

        assert process_max_update(session, update, sender) == {
            "ok": True,
            "bridge": "retried",
            "target": "telegram",
        }
        delivery = session.scalar(select(MessagingBridgeDelivery))
        assert delivery.status == "delivered"
        assert delivery.attempts == 2
        assert sender.sent == [("-10002", "<b>Из MAX · Павел</b>\nНе терять", None)]


def test_max_channel_update_is_never_injected_into_the_telegram_practice_chat():
    with make_session() as session:
        session.add(
            MessagingBridgePair(
                key="max-channel",
                status="active",
                telegram_channel_id="-10001",
                max_channel_id="101",
                telegram_practice_chat_id="-10002",
                max_practice_chat_id="102",
            )
        )
        session.commit()
        sender = FakeTelegramSender()
        result = process_max_update(
            session,
            {
                "update_type": "message_created",
                "timestamp": 99,
                "message": {
                    "recipient": {"chat_id": "101"},
                    "sender": {"name": "Админ"},
                    "body": {"mid": "channel-1", "text": "Не в чат практики"},
                },
            },
            sender,
        )
        assert result == {"ok": True, "bridge": "ignored_channel"}
        assert sender.sent == []


def test_max_edit_and_remove_update_the_telegram_copy_only_for_max_source():
    with make_session() as session:
        pair = MessagingBridgePair(
            key="sprint-edit",
            status="active",
            telegram_channel_id="-10001",
            max_channel_id="101",
            telegram_practice_chat_id="-10002",
            max_practice_chat_id="102",
        )
        session.add(pair)
        session.flush()
        mapped = MessagingBridgeMessage(
            pair_id=pair.id,
            kind="practice",
            telegram_message_id="31",
            max_message_id="max-31",
            source_platform="max",
            source_author_name="Павел",
        )
        session.add(mapped)
        session.commit()
        sender = FakeTelegramSender()

        assert process_max_update(
            session,
            {
                "update_type": "message_edited",
                "timestamp": 2,
                "message": {
                    "recipient": {"chat_id": "102"},
                    "body": {"mid": "max-31", "text": "Исправил"},
                },
            },
            sender,
        )["bridge"] == "edited"
        assert sender.edited == [("-10002", "31", "<b>Из MAX · Павел</b>\nИсправил")]

        assert process_max_update(
            session,
            {
                "update_type": "message_removed",
                "timestamp": 3,
                "message_id": "max-31",
                "chat_id": "102",
            },
            sender,
        )["bridge"] == "removed"
        assert sender.deleted == [("-10002", "31")]


def test_cross_messenger_max_webhook_requires_its_own_secret_and_mirrors_message(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'cross-messenger.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            MessagingBridgePair(
                key="webhook-pair",
                status="test",
                telegram_channel_id="-10001",
                max_channel_id="101",
                telegram_practice_chat_id="-10002",
                max_practice_chat_id="102",
            )
        )
        session.commit()

    def db_override():
        with Session(engine) as session:
            yield session

    sender = FakeTelegramSender()
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module, "client", lambda: sender)
    monkeypatch.setattr(main_module.settings, "bridge_max_webhook_secret", "relay-secret")
    client = TestClient(app)
    update = {
        "update_type": "message_created",
        "timestamp": 4,
        "message": {
            "recipient": {"chat_id": "102"},
            "sender": {"name": "Павел"},
            "body": {"mid": "max-webhook-1", "text": "Проверка"},
        },
    }
    try:
        assert client.post("/bot/cross-messenger/max/webhook", json=update).status_code == 403
        response = client.post(
            "/bot/cross-messenger/max/webhook",
            json=update,
            headers={"X-Max-Bot-Api-Secret": "relay-secret"},
        )
        assert response.json()["bridge"] == "mirrored"
        assert sender.sent == [("-10002", "<b>Из MAX · Павел</b>\nПроверка", None)]
    finally:
        app.dependency_overrides.clear()


def test_telegram_webhook_requires_its_secret_before_a_pair_can_deliver(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'telegram-webhook.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            MessagingBridgePair(
                key="telegram-webhook-pair",
                status="test",
                telegram_channel_id="-10001",
                max_channel_id="101",
                telegram_practice_chat_id="-10002",
                max_practice_chat_id="102",
            )
        )
        session.commit()

    def db_override():
        with Session(engine) as session:
            yield session

    sender = FakeMaxSender()
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module, "bridge_max_client", lambda: sender)
    monkeypatch.setattr(main_module.settings, "telegram_webhook_secret", "telegram-secret")
    client = TestClient(app)
    update = {
        "update_id": 501,
        "channel_post": {"message_id": 1, "chat": {"id": -10001}, "text": "Проверка"},
    }
    try:
        assert client.post("/telegram/webhook", json=update).status_code == 403
        assert client.post(
            "/telegram/webhook",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        ).status_code == 403
        response = client.post(
            "/telegram/webhook",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-secret"},
        )
        assert response.json()["bridge"] == "mirrored"
        assert sender.sent == [("101", "Проверка", None)]
    finally:
        app.dependency_overrides.clear()
