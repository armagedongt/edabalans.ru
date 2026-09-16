from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.database import get_db
from app.max import MaxClient
from app.max_health import MaxHealth, check_max_dependencies


WEBHOOK = "https://example.test/api/messaging/max/webhook"
REQUIRED_EVENTS = {"bot_started", "bot_stopped", "dialog_removed", "message_created", "message_callback"}


def sender(me=None, subscriptions=None, status=200):
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "test-token"
        body = ({"is_bot": True} if me is None else me) if request.url.path == "/me" else (
            {"subscriptions": [{"url": WEBHOOK, "update_types": list(REQUIRED_EVENTS)}]}
            if subscriptions is None else subscriptions
        )
        return httpx.Response(status, json=body)

    return MaxClient("test-token", transport=httpx.MockTransport(respond)), calls


def test_max_check_is_read_only_and_checks_api_and_webhook():
    api, calls = sender()
    assert check_max_dependencies(api, WEBHOOK) == []
    assert [call.url.path for call in calls] == ["/me", "/subscriptions"]


@pytest.mark.parametrize(("subscriptions", "reason"), [
    ({"subscriptions": []}, "max_webhook_missing"),
    ({"subscriptions": [{"url": WEBHOOK + "/wrong"}]}, "max_webhook_missing"),
    ({"subscriptions": [{"url": WEBHOOK, "update_types": ["bot_started"]}]}, "max_webhook_events_missing"),
    ({"subscriptions": "invalid"}, "max_unexpected_subscriptions_response"),
])
def test_missing_or_wrong_webhook_is_not_ready(subscriptions, reason):
    api, _ = sender(subscriptions=subscriptions)
    assert check_max_dependencies(api, WEBHOOK) == [reason]


def test_webhook_with_all_event_types_is_accepted():
    api, _ = sender(subscriptions={"subscriptions": [{"url": WEBHOOK}]})
    assert check_max_dependencies(api, WEBHOOK) == []


@pytest.mark.parametrize("missing", sorted(REQUIRED_EVENTS))
def test_each_required_webhook_event_is_checked(missing):
    api, _ = sender(subscriptions={"subscriptions": [{"url": WEBHOOK, "update_types": list(REQUIRED_EVENTS - {missing})}]})
    assert check_max_dependencies(api, WEBHOOK) == ["max_webhook_events_missing"]


def test_unexpected_me_response_is_not_ready():
    api, _ = sender(me={"is_bot": False})
    assert check_max_dependencies(api, WEBHOOK) == ["max_unexpected_bot_response"]


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_api_http_errors_are_reported_without_secrets(status):
    api, _ = sender(status=status)
    assert check_max_dependencies(api, WEBHOOK) == [f"max_api_http_{status}"]


def test_api_network_errors_are_not_ready():
    def fail(request):
        raise httpx.ConnectError("sensitive upstream details", request=request)
    api = MaxClient("test-token", transport=httpx.MockTransport(fail))
    assert check_max_dependencies(api, WEBHOOK) == ["max_api_unreachable"]


def test_cached_check_expires_even_if_previous_result_was_healthy():
    health = MaxHealth(checked_at=100, reasons=[])
    assert health.failure_reasons(now=175) == []
    assert health.failure_reasons(now=176) == ["max_check_stale"]


@pytest.mark.parametrize(("status", "body", "reason"), [
    (200, {"ok": True, "ignored": True}, None),
    (403, {}, "max_webhook_http_403"),
    (503, {}, "max_webhook_http_503"),
    (200, {"status": "ready"}, "max_webhook_unexpected_response"),
])
def test_synthetic_probe_verifies_actual_webhook_route_and_authentication(status, body, reason):
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path == "/me":
            return httpx.Response(200, json={"is_bot": True})
        if request.url.path == "/subscriptions":
            return httpx.Response(200, json={"subscriptions": [{"url": WEBHOOK}]})
        assert str(request.url) == WEBHOOK
        assert request.method == "POST"
        assert request.headers["X-Max-Bot-Api-Secret"] == "test-webhook-secret"
        assert "runtime_health_probe" in request.content.decode()
        return httpx.Response(status, json=body)
    api = MaxClient("test-token", transport=httpx.MockTransport(respond))
    assert check_max_dependencies(api, WEBHOOK, "test-webhook-secret") == ([reason] if reason else [])
    assert len(calls) == 3


@pytest.fixture
def health_client(monkeypatch):
    class Database:
        def execute(self, statement):
            return None
    app = main.app
    app.dependency_overrides[get_db] = lambda: Database()
    monkeypatch.setattr(main.settings, "max_bot_token", "test-token")
    monkeypatch.setattr(main.settings, "max_webhook_secret", "test-secret")
    monkeypatch.setattr(main.settings, "telegram_public_base_url", "https://example.test")
    monkeypatch.setattr(main.settings, "scheduler_enabled", True)
    monkeypatch.setattr(main.runtime_health, "last_scheduler_activity", time.monotonic())
    monkeypatch.setattr(main.runtime_health, "scheduler_failed", False)
    monkeypatch.setattr(main, "max_health", MaxHealth(checked_at=time.monotonic(), reasons=[]))
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_public_max_health_uses_cache_and_does_not_require_telegram(health_client, monkeypatch):
    monkeypatch.setattr(main.settings, "telegram_test_bot_token", "")
    monkeypatch.setattr(main.settings, "telegram_polling_enabled", False)
    monkeypatch.setattr(main, "max_client", lambda: pytest.fail("public health must not call MAX"))
    for _ in range(3):
        response = health_client.get("/ready/max")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "reasons": [], "messenger": "max"}
        assert response.headers["cache-control"] == "no-store"


def test_real_webhook_ignores_authenticated_probe_without_contact_or_message(health_client):
    response = health_client.post("/bot/max/webhook", json={"update_type": "runtime_health_probe"},
                                  headers={"X-Max-Bot-Api-Secret": "test-secret"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "ignored": True}


@pytest.mark.parametrize(("setting", "reason"), [
    ("max_bot_token", "max_token_missing"),
    ("max_webhook_secret", "max_webhook_secret_missing"),
    ("telegram_public_base_url", "max_public_url_missing"),
])
def test_max_missing_configuration_fails_closed(health_client, monkeypatch, setting, reason):
    monkeypatch.setattr(main.settings, setting, "")
    response = health_client.get("/ready/max")
    assert response.status_code == 503
    assert reason in response.json()["reasons"]


def test_max_dependency_failure_is_visible(health_client):
    main.max_health.reasons = ["max_api_http_429"]
    response = health_client.get("/ready/max")
    assert response.status_code == 503
    assert response.json()["reasons"] == ["max_api_http_429"]


def test_max_requires_live_scheduler(health_client):
    main.runtime_health.last_scheduler_activity = time.monotonic() - 360
    assert "scheduler_stale" in health_client.get("/ready/max").json()["reasons"]


def test_max_requires_database(health_client):
    class BrokenDatabase:
        def execute(self, statement):
            raise RuntimeError("database failed")
    main.app.dependency_overrides[get_db] = lambda: BrokenDatabase()
    response = health_client.get("/ready/max")
    assert response.status_code == 503
    assert "database_unavailable" in response.json()["reasons"]


def test_background_max_check_recovers_after_failure(monkeypatch):
    health = MaxHealth()
    monkeypatch.setattr(main, "max_health", health)
    monkeypatch.setattr(main, "max_client", lambda: object())
    results = iter([["max_api_unreachable"], []])
    monkeypatch.setattr(main, "check_max_dependencies", lambda *args: next(results))
    sleeps = []
    async def sleep(delay):
        sleeps.append(list(health.reasons))
        if len(sleeps) == 2:
            raise asyncio.CancelledError()
    monkeypatch.setattr(main.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.max_health_loop())
    assert sleeps == [["max_api_unreachable"], []]
    assert health.checked_at is not None


def test_lifespan_starts_max_check_and_cancels_it_on_shutdown(monkeypatch):
    from contextlib import nullcontext

    monkeypatch.setattr(main.settings, "auto_create_schema", False)
    monkeypatch.setattr(main.settings, "max_bot_token", "test-token")
    monkeypatch.setattr(main.settings, "scheduler_enabled", False)
    monkeypatch.setattr(main.settings, "telegram_polling_enabled", False)
    monkeypatch.setattr(main.settings, "yandex_metrika_offline_enabled", False)
    monkeypatch.setattr(main, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(main, "seed_defaults", lambda *args, **kwargs: None)
    events = []

    async def fake_max_loop():
        events.append("started")
        try:
            await asyncio.Event().wait()
        finally:
            events.append("stopped")

    monkeypatch.setattr(main, "max_health_loop", fake_max_loop)

    async def exercise():
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
            assert events == ["started"]
        await asyncio.sleep(0)
        assert events == ["started", "stopped"]

    asyncio.run(exercise())
