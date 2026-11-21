from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import Settings
from app.models import MasterclassNotification, OwnerPaymentAlertDelivery
from app import owner_notification_delivery as completion
from app.masterclass_dispatch import dispatch_due_masterclass_notifications
from app.telegram import TelegramError
from test_messenger_routing import _session


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    session = _session(tmp_path)
    settings = Settings(telegram_test_bot_token="123:synthetic",
                        technical_telegram_recipient_ids="111,222")
    now = datetime.now(UTC)
    notification = MasterclassNotification(user_id=str(uuid4()), notification_kind="strength_workout_completed",
        deduplication_key=str(uuid4()), due_at=now, expires_at=now+timedelta(days=1),
        payload={"message_text": "<b>Клиент потренировался</b>\nКлиент: Тест"})
    session.add(notification)
    session.commit()
    calls = []
    client = SimpleNamespace(call=lambda *a: {"id": 123, "username": "fixture_bot"})
    def send(recipient, message):
        calls.append((recipient, message))
        return str(len(calls))
    client.send_html_message = send
    def make_telegram(token, **kwargs):
        client.actual_token = token
        client.call = lambda *args: {"id": int(token.split(":")[0]), "username": "fixture_bot"}
        return client
    monkeypatch.setattr(completion, "TelegramClient", make_telegram)
    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: settings)
    yield session, notification, settings, client, calls
    session.close()


def test_owner_alert_uses_both_configured_recipients_and_shared_receipts(fixture):
    session, notification, settings, client, calls = fixture
    # No linked client contact or course access is needed for an owner alert.
    result = dispatch_due_masterclass_notifications(session, None, "", test_only=True)
    assert result["sent"] == 1 and notification.status == "sent"
    assert [x[0] for x in calls] == ["111", "222"]
    assert notification.payload["delivery_bot_username"] == "fixture_bot"
    assert set(notification.payload["deliveries"]) == {"111", "222"}
    assert all(x.status == "sent" for x in session.scalars(select(OwnerPaymentAlertDelivery)))
    completion.deliver_owner_notification(session, notification, settings)
    assert len(calls) == 2


def test_partial_rejection_retry_does_not_repeat_success(fixture):
    session, notification, settings, client, calls = fixture
    original = client.send_html_message
    def reject_second(recipient, message):
        if recipient == "222":
            raise TelegramError("Telegram API HTTP 429: Too many requests")
        return original(recipient, message)
    client.send_html_message = reject_second
    result = dispatch_due_masterclass_notifications(session, None, "")
    assert result["failed"] == 1 and notification.status == "retrying"
    assert [x[0] for x in calls] == ["111"]
    notification.due_at = datetime.now(UTC)-timedelta(seconds=1)
    session.commit()
    client.send_html_message = original
    assert dispatch_due_masterclass_notifications(session, None, "")["sent"] == 1
    assert [x[0] for x in calls] == ["111", "222"]
    rows = list(session.scalars(select(OwnerPaymentAlertDelivery)))
    assert sorted(x.attempt_count for x in rows) == [1, 2]


def test_lost_ack_is_recorded_and_never_automatically_resent(fixture):
    session, notification, settings, client, calls = fixture
    def lost_ack(recipient, message):
        calls.append(recipient)
        raise TimeoutError("token URL must not be stored")
    client.send_html_message = lost_ack
    assert dispatch_due_masterclass_notifications(session, None, "")["failed"] == 1
    assert notification.status == "failed" and "token URL" not in notification.error_message
    assert all(row.status == "unconfirmed" for row in session.scalars(select(OwnerPaymentAlertDelivery)))
    with pytest.raises(RuntimeError, match="unconfirmed"):
        completion.deliver_owner_notification(session, notification, settings)
    assert len(calls) == 2


def test_max_dispatch_does_not_send_or_consume_owner_alert(fixture):
    session, notification, _, _, calls = fixture
    dispatch_due_masterclass_notifications(session, None, "", platform="max")
    assert notification.status == "pending" and not calls


def planning_route(notification, settings):
    notification.notification_kind = "owner_planning_summary"
    notification.payload = {"message_text": "План на сегодня", "delivery_role": "planning"}
    settings.planning_telegram_bot_token = "456:planning-synthetic"
    settings.planning_telegram_bot_id = "456"
    settings.planning_telegram_recipient_id = "333"


def test_planning_only_uses_personal_bot_and_one_recipient_with_durable_receipt(fixture):
    session, notification, settings, client, calls = fixture
    planning_route(notification, settings)
    session.commit()
    assert dispatch_due_masterclass_notifications(session, None, "", test_only=True)["sent"] == 1
    assert [x[0] for x in calls] == ["333"]
    assert client.actual_token == "456:planning-synthetic"
    assert notification.payload["delivery_bot_id"] == "456"
    assert notification.payload["delivery_role"] == "planning"
    completion.deliver_owner_notification(session, notification, settings)
    assert len(calls) == 1


@pytest.mark.parametrize("case", ["token", "identity", "recipient", "frozen_recipient"])
def test_planning_never_falls_back_to_other_bots_or_recipients(fixture, case):
    session, notification, settings, client, calls = fixture
    planning_route(notification, settings)
    if case == "token": settings.planning_telegram_bot_token = ""
    if case == "identity": settings.planning_telegram_bot_id = "999"
    if case == "recipient": settings.planning_telegram_recipient_id = "333,222"
    if case == "frozen_recipient": notification.payload = {**notification.payload, "delivery_recipients": ["222"]}
    session.commit()
    assert dispatch_due_masterclass_notifications(session, None, "")["failed"] == 1
    assert not calls


def test_planning_max_and_expired_summaries_never_send(fixture):
    session, notification, settings, client, calls = fixture
    planning_route(notification, settings); session.commit()
    dispatch_due_masterclass_notifications(session, None, "", platform="max")
    assert notification.status == "pending" and not calls
    notification.expires_at = datetime.now(UTC) - timedelta(seconds=1); session.commit()
    dispatch_due_masterclass_notifications(session, None, "")
    assert notification.status == "failed" and not calls
