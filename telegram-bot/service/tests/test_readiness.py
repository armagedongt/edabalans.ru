from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.main as main_module
from app.database import Base, get_db, make_engine
from app.main import app


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


def test_ready_confirms_database_polling_scheduler_and_proxy(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "reasons": []}
    app.dependency_overrides.clear()


def test_ready_fails_when_telegram_polling_is_stale(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    main_module.runtime_health.last_poll_success = time.monotonic() - 120

    response = client.get("/ready")

    assert response.status_code == 503
    assert "polling_stale" in response.json()["reasons"]
    app.dependency_overrides.clear()


def test_ready_fails_when_european_proxy_is_not_configured(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module.settings, "telegram_proxy_url", "")

    response = client.get("/ready")

    assert response.status_code == 503
    assert "telegram_proxy_missing" in response.json()["reasons"]
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


def test_polling_success_is_recorded_only_after_get_updates_through_proxy(monkeypatch):
    observed: dict[str, object] = {"calls": 0}

    class FakePollingTelegram:
        def __init__(self, token, *, proxy_url, channel_id):
            observed["token"] = token
            observed["proxy_url"] = proxy_url
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
    monkeypatch.setattr(main_module.settings, "telegram_channel_id", "channel")
    monkeypatch.setattr(main_module, "TelegramClient", FakePollingTelegram)
    main_module.runtime_health.last_poll_success = None

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_module.polling_loop())

    assert observed["proxy_url"] == "socks5://eu-gateway.example.test:1080"
    assert observed["webhook_removed"] is True
    assert main_module.runtime_health.last_poll_success is not None


def test_polling_failure_does_not_record_success(monkeypatch):
    class FailedPollingTelegram:
        def __init__(self, token, *, proxy_url, channel_id):
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
    main_module.runtime_health.last_scheduler_activity = 123.0
    main_module.runtime_health.scheduler_failed = True

    main_module.scheduler_iteration()

    assert main_module.runtime_health.last_scheduler_activity > 123.0
    assert main_module.runtime_health.scheduler_failed is False
