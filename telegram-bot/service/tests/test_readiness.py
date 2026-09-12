from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main_module
import app.telegram as telegram_module
from app.database import Base, get_db, make_engine
from app.main import app
from app.models import TrackingEvent, UpdateReceipt
from app.seed import seed_defaults


def _client(tmp_path, monkeypatch) -> TestClient:
    engine = make_engine(f"sqlite:///{tmp_path / 'readiness.sqlite'}")
    Base.metadata.create_all(engine)

    def db_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module.settings, "telegram_test_bot_token", "test-token")
    monkeypatch.setattr(main_module.settings, "telegram_proxy_url", "socks5://proxy.example.test:1080")
    monkeypatch.setattr(main_module.settings, "telegram_polling_enabled", True)
    monkeypatch.setattr(main_module.settings, "scheduler_enabled", True)
    now = time.monotonic()
    main_module.runtime_health.last_poll_success = now
    main_module.runtime_health.last_scheduler_activity = now
    main_module.runtime_health.scheduler_failed = False
    return TestClient(app)


def test_ready_confirms_database_polling_scheduler_and_telegram_route(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "reasons": [], "telegram_route": "proxy"}
    app.dependency_overrides.clear()


def test_ready_fails_when_telegram_polling_is_stale(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    main_module.runtime_health.last_poll_success = time.monotonic() - 120

    response = client.get("/ready")

    assert response.status_code == 503
    assert "polling_stale" in response.json()["reasons"]
    app.dependency_overrides.clear()


def test_ready_accepts_the_current_direct_telegram_route(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module.settings, "telegram_proxy_url", "")

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["telegram_route"] == "direct"
    app.dependency_overrides.clear()


def test_ready_reports_relay_route(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module.settings, "telegram_proxy_url", "http://legacy-proxy.example.test:3128")
    monkeypatch.setattr(main_module.settings, "telegram_api_base_url", "https://relay.example.test/telegram")
    monkeypatch.setattr(main_module.settings, "telegram_gateway_token", "relay-secret")

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["telegram_route"] == "relay"
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("setting", "value", "reason"),
    [
        ("telegram_test_bot_token", "", "telegram_token_missing"),
        ("telegram_polling_enabled", False, "polling_disabled"),
        ("scheduler_enabled", False, "scheduler_disabled"),
    ],
)
def test_ready_fails_when_required_runtime_configuration_is_disabled(
    tmp_path, monkeypatch, setting, value, reason
):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module.settings, setting, value)

    response = client.get("/ready")

    assert response.status_code == 503
    assert reason in response.json()["reasons"]
    app.dependency_overrides.clear()


def test_ready_fails_when_scheduler_is_stale(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    main_module.runtime_health.last_scheduler_activity = time.monotonic() - 360

    response = client.get("/ready")

    assert response.status_code == 503
    assert "scheduler_stale" in response.json()["reasons"]
    app.dependency_overrides.clear()


def test_ready_fails_immediately_after_scheduler_error(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    main_module.runtime_health.scheduler_failed = True

    response = client.get("/ready")

    assert response.status_code == 503
    assert "scheduler_failed" in response.json()["reasons"]
    app.dependency_overrides.clear()


def test_ready_fails_when_database_is_unavailable(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    class BrokenDatabase:
        def execute(self, _statement):
            raise RuntimeError("database unavailable")

    def broken_db_override():
        yield BrokenDatabase()

    app.dependency_overrides[get_db] = broken_db_override
    response = client.get("/ready")

    assert response.status_code == 503
    assert "database_unavailable" in response.json()["reasons"]
    app.dependency_overrides.clear()


def test_polling_success_uses_the_configured_relay_route(monkeypatch):
    observed: dict[str, object] = {"calls": 0}

    class FakePollingTelegram:
        def __init__(self, token, *, proxy_url, api_base_url, gateway_token, channel_id):
            observed["token"] = token
            observed["proxy_url"] = proxy_url
            observed["api_base_url"] = api_base_url
            observed["gateway_token"] = gateway_token
            observed["channel_id"] = channel_id

        def delete_webhook(self):
            observed["webhook_removed"] = True

        def get_updates(self, offset, timeout):
            observed["calls"] = int(observed["calls"]) + 1
            if observed["calls"] == 1:
                return []
            raise asyncio.CancelledError

    monkeypatch.setattr(main_module.settings, "telegram_test_bot_token", "test-token")
    monkeypatch.setattr(main_module.settings, "telegram_proxy_url", "socks5://eu-gateway.example.test:1080")
    monkeypatch.setattr(main_module.settings, "telegram_api_base_url", "https://relay.example.test/telegram")
    monkeypatch.setattr(main_module.settings, "telegram_gateway_token", "relay-secret")
    monkeypatch.setattr(main_module.settings, "telegram_channel_id", "channel")
    monkeypatch.setattr(main_module, "TelegramClient", FakePollingTelegram)
    main_module.runtime_health.last_poll_success = None

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_module.polling_loop())

    assert observed["proxy_url"] == "socks5://eu-gateway.example.test:1080"
    assert observed["api_base_url"] == "https://relay.example.test/telegram"
    assert observed["gateway_token"] == "relay-secret"
    assert observed["webhook_removed"] is True
    assert main_module.runtime_health.last_poll_success is not None


def test_response_and_scheduler_clients_receive_the_relay_configuration(monkeypatch):
    calls = []

    class FakeTelegram:
        def __init__(self, token, **options):
            calls.append((token, options))

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, _query):
            return self

        def all(self):
            return []

    monkeypatch.setattr(main_module.settings, "telegram_test_bot_token", "test-token")
    monkeypatch.setattr(main_module.settings, "telegram_proxy_url", "http://legacy-proxy.example.test:3128")
    monkeypatch.setattr(main_module.settings, "telegram_api_base_url", "https://relay.example.test/telegram")
    monkeypatch.setattr(main_module.settings, "telegram_gateway_token", "relay-secret")
    monkeypatch.setattr(main_module.settings, "telegram_channel_id", "channel")
    monkeypatch.setattr(main_module.settings, "max_bot_token", "")
    monkeypatch.setattr(main_module, "TelegramClient", FakeTelegram)
    monkeypatch.setattr(main_module, "SessionLocal", FakeSession)
    monkeypatch.setattr(main_module, "stop_presale_runs_from_purchase_events", lambda _session: 0)
    monkeypatch.setattr(main_module, "reconcile_masterclass_presale_runs", lambda _session: 0)
    monkeypatch.setattr(main_module, "due_runs", lambda _session: [])
    monkeypatch.setattr(main_module, "dispatch_masterclass_notifications", lambda _session, _tg: 0)

    main_module.client()
    main_module.scheduler_iteration()

    assert len(calls) == 2
    for token, options in calls:
        assert token == "test-token"
        assert options["api_base_url"] == "https://relay.example.test/telegram"
        assert options["gateway_token"] == "relay-secret"
        assert options["proxy_url"] == "http://legacy-proxy.example.test:3128"


def test_real_telegram_client_applies_configured_proxy_to_httpx(monkeypatch):
    observed: dict[str, object] = {}
    sentinel = object()

    def fake_httpx_client(**options):
        observed.update(options)
        return sentinel

    monkeypatch.setattr(telegram_module.httpx, "Client", fake_httpx_client)
    client = telegram_module.TelegramClient(
        "test-token", proxy_url="socks5://eu-gateway.example.test:1080"
    )

    assert client._client(12) is sentinel
    assert observed["proxy"] == "socks5://eu-gateway.example.test:1080"
    assert observed["timeout"] == 12


def test_polling_failure_does_not_record_success(monkeypatch):
    class FailedPollingTelegram:
        def __init__(self, token, *, proxy_url, api_base_url, gateway_token, channel_id):
            pass

        def delete_webhook(self):
            pass

        def get_updates(self, offset, timeout):
            raise RuntimeError("proxy unavailable")

    async def stop_after_retry(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(main_module.settings, "telegram_test_bot_token", "test-token")
    monkeypatch.setattr(main_module.settings, "telegram_proxy_url", "socks5://eu-gateway.example.test:1080")
    monkeypatch.setattr(main_module, "TelegramClient", FailedPollingTelegram)
    monkeypatch.setattr(main_module.asyncio, "sleep", stop_after_retry)
    main_module.runtime_health.last_poll_success = None

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_module.polling_loop())

    assert main_module.runtime_health.last_poll_success is None


def test_poison_update_is_dead_lettered_after_bounded_retries(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'polling-dead-letter.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "TetrisgfgfgfBot")

    offsets = []

    class PoisonPollingTelegram:
        def __init__(self, token, *, proxy_url, api_base_url, gateway_token, channel_id):
            pass

        def delete_webhook(self):
            pass

        def get_updates(self, offset, timeout):
            offsets.append(offset)
            if offset is not None:
                raise asyncio.CancelledError
            return [{"update_id": 777, "message": {"text": "/start"}}]

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(main_module.settings, "telegram_test_bot_token", "test-token")
    monkeypatch.setattr(main_module, "TelegramClient", PoisonPollingTelegram)
    monkeypatch.setattr(main_module, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(main_module, "process_update", lambda _update, _session: (_ for _ in ()).throw(RuntimeError("poison")))
    monkeypatch.setattr(main_module.asyncio, "sleep", no_wait)
    main_module.telegram_update_failures.clear()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_module.polling_loop())

    assert offsets == [None, None, None, 778]
    with Session(engine) as session:
        receipt = session.scalar(select(UpdateReceipt).where(UpdateReceipt.update_type == "dead_letter"))
        event = session.scalar(select(TrackingEvent).where(
            TrackingEvent.event_type == "telegram_update_dead_letter"
        ))
        assert receipt is not None
        assert event.metadata_json["attempts"] == 3


def test_scheduler_gets_startup_grace_before_first_iteration(monkeypatch):
    def stop_iteration():
        raise asyncio.CancelledError

    monkeypatch.setattr(main_module, "scheduler_iteration", stop_iteration)
    main_module.runtime_health.last_scheduler_activity = None

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_module.scheduler_loop())

    assert main_module.runtime_health.last_scheduler_activity is not None


def test_scheduler_failure_does_not_refresh_existing_activity(monkeypatch):
    existing_activity = 123.0

    def fail_iteration():
        raise RuntimeError("scheduler failed")

    async def stop_after_retry(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(main_module, "scheduler_iteration", fail_iteration)
    monkeypatch.setattr(main_module.asyncio, "sleep", stop_after_retry)
    main_module.runtime_health.last_scheduler_activity = existing_activity
    main_module.runtime_health.scheduler_failed = False

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_module.scheduler_loop())

    assert main_module.runtime_health.last_scheduler_activity == existing_activity
    assert main_module.runtime_health.scheduler_failed is True


def test_successful_scheduler_iteration_refreshes_activity(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'scheduler.sqlite'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main_module, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(main_module.settings, "telegram_test_bot_token", "")
    monkeypatch.setattr(main_module.time, "monotonic", lambda: 456.0)
    main_module.runtime_health.last_scheduler_activity = 123.0
    main_module.runtime_health.scheduler_failed = True

    main_module.scheduler_iteration()

    assert main_module.runtime_health.last_scheduler_activity == 456.0
    assert main_module.runtime_health.scheduler_failed is False


def test_metrika_sync_runs_at_configured_interval(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'scheduler-metrika.sqlite'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main_module, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(main_module.settings, "telegram_test_bot_token", "")
    monkeypatch.setattr(main_module.settings, "yandex_metrika_offline_enabled", True)
    monkeypatch.setattr(main_module.settings, "yandex_oauth_token", "secret")
    monkeypatch.setattr(main_module.settings, "yandex_metrika_counter_id", 97331502)
    monkeypatch.setattr(main_module.settings, "yandex_metrika_offline_interval_seconds", 60)
    monkeypatch.setattr(main_module.time, "monotonic", lambda: 500.0)
    calls = []
    monkeypatch.setattr(main_module, "MetrikaOfflineClient", lambda token, counter: (token, counter))
    monkeypatch.setattr(main_module, "sync_offline_conversions", lambda session, client: calls.append(client))
    main_module.last_metrika_sync_monotonic = None

    main_module.metrika_sync_iteration()
    main_module.metrika_sync_iteration()

    assert calls == [("secret", 97331502)]
    assert main_module.runtime_health.scheduler_failed is False


def test_metrika_failure_is_retryable_next_interval(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'scheduler-metrika-failure.sqlite'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main_module, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(main_module.settings, "telegram_test_bot_token", "")
    monkeypatch.setattr(main_module.settings, "yandex_metrika_offline_enabled", True)
    monkeypatch.setattr(main_module.settings, "yandex_oauth_token", "secret")
    monkeypatch.setattr(main_module.settings, "yandex_metrika_counter_id", 97331502)
    monkeypatch.setattr(main_module.settings, "yandex_metrika_offline_interval_seconds", 60)
    clock = {"value": 500.0}
    monkeypatch.setattr(main_module.time, "monotonic", lambda: clock["value"])
    attempts = []

    def fail_sync(session, client):
        attempts.append(clock["value"])
        raise RuntimeError("temporary Yandex failure")

    monkeypatch.setattr(main_module, "MetrikaOfflineClient", lambda token, counter: object())
    monkeypatch.setattr(main_module, "sync_offline_conversions", fail_sync)
    main_module.last_metrika_sync_monotonic = None

    with pytest.raises(RuntimeError, match="temporary Yandex failure"):
        main_module.metrika_sync_iteration()
    clock["value"] = 561.0
    with pytest.raises(RuntimeError, match="temporary Yandex failure"):
        main_module.metrika_sync_iteration()

    assert attempts == [500.0, 561.0]
    assert main_module.runtime_health.scheduler_failed is False


def test_metrika_loop_is_independent_from_message_scheduler(monkeypatch):
    calls = []

    def stop_iteration():
        calls.append("metrika")
        raise asyncio.CancelledError

    monkeypatch.setattr(main_module.settings, "scheduler_enabled", False)
    monkeypatch.setattr(main_module, "metrika_sync_iteration", stop_iteration)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_module.metrika_sync_loop())

    assert calls == ["metrika"]


def test_broadcast_refreshes_scheduler_activity_between_recipients(monkeypatch):
    monkeypatch.setattr(main_module.time, "monotonic", lambda: 456.0)
    recipients = [
        type("Recipient", (), {"contact_id": 1, "status": "pending"})(),
        type("Recipient", (), {"contact_id": 2, "status": "pending"})(),
    ]
    contacts = {
        item_id: type(
            "Contact",
            (),
            {"chat_id": str(item_id), "telegram_user_id": str(item_id), "status": "active"},
        )()
        for item_id in (1, 2)
    }
    content = type("Content", (), {"code": "test"})()
    row = type(
        "BroadcastRow",
        (),
        {
            "id": 1,
            "started_at": None,
            "status": "pending",
            "segment": {},
            "content_item_id": 2,
            "finished_at": None,
        },
    )()

    class FakeSession:
        def scalars(self, _query):
            return recipients

        def get(self, model, item_id):
            return content if model is main_module.ContentItem else contacts[item_id]

        def commit(self):
            pass

    class FakeTelegram:
        calls = 0

        def send_content(self, chat_id, sent_content, configuration):
            self.calls += 1
            if self.calls == 2:
                assert main_module.runtime_health.last_scheduler_activity == 456.0
            assert sent_content is content
            return f"message-{self.calls}"

    main_module.runtime_health.last_scheduler_activity = 123.0

    sent, failed = main_module._deliver_broadcast(FakeSession(), row, FakeTelegram())

    assert (sent, failed) == (2, 0)
    assert main_module.runtime_health.last_scheduler_activity == 456.0
