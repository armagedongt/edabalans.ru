import json
import hashlib
import re
import ssl
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from urllib.parse import parse_qs, urlparse

import app.main as main_module
from app.database import Base, get_db, make_engine
from app.main import app
from app.max import MAX_CA_BUNDLE, MaxClient
from app.models import (
    AccountCredential,
    AccountOnboarding,
    CrmAttributionEvent,
    CrmMessengerAccount,
    CrmTag,
    CrmUser,
    CrmUserTag,
    MessengerLinkToken,
    TrackingEvent,
    UpdateReceipt,
)
from app.seed import seed_defaults


class FakeMax:
    def __init__(self):
        self.sent = []

    def send_html(self, user_id, text, **kwargs):
        self.sent.append((user_id, text, kwargs))
        return "1"


def test_max_ca_bundle_loads_without_changing_system_trust():
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(MAX_CA_BUNDLE))
    assert MAX_CA_BUNDLE.is_file()


def test_max_client_sends_link_button():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"message": {"body": {"mid": "max-message-1"}}})

    message_id = MaxClient("max-secret", httpx.MockTransport(handler)).send_html(
        "901",
        "<b>Интенсив</b>",
        button_text="Открыть первый день",
        button_url="https://app.edabalans.ru/intensive/start?i=Etoken",
    )

    request = captured["request"]
    assert message_id == "max-message-1"
    assert request.headers["Authorization"] == "max-secret"
    assert request.url.params["user_id"] == "901"
    payload = json.loads(request.content)
    assert payload["attachments"] == [{
        "type": "inline_keyboard",
        "payload": {"buttons": [[{
            "type": "link",
            "text": "Открыть первый день",
            "url": "https://app.edabalans.ru/intensive/start?i=Etoken",
        }]]},
    }]


def max_start(timestamp="2026-08-27T10:00:00Z", payload=""):
    return {
        "update_type": "bot_started",
        "timestamp": timestamp,
        "user": {"user_id": 901, "name": "MAX visitor", "username": "max_visitor"},
        "payload": payload,
    }


def make_client(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'max.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        session.add(CrmTag(code="pikabu", name="Пикабу", category="source", status="active"))
        session.commit()

    def db_override():
        with Session(engine) as session:
            yield session

    fake = FakeMax()
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module, "max_client", lambda: fake)
    monkeypatch.setattr(main_module.settings, "max_webhook_secret", "test-secret")
    monkeypatch.setattr(main_module.settings, "max_bot_username", "id230409966750_bot")
    monkeypatch.setattr(main_module.settings, "app_auth_secret", "test-app-auth-secret")
    return TestClient(app), engine, fake


def test_max_start_saves_identity_and_sends_intensive_link(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}
    response = client.post("/bot/max/webhook", json=max_start(), headers=headers)
    assert response.json() == {"ok": True, "intensive": True, "first_start": True}
    assert client.post("/bot/max/webhook", json=max_start(), headers=headers).json() == {"ok": True, "duplicate": True}
    assert len(fake.sent) == 1
    assert fake.sent[0][0] == "901"
    assert "Бесплатный интенсив" in fake.sent[0][1]
    assert fake.sent[0][2]["button_text"] == "Открыть первый день"
    assert fake.sent[0][2]["button_url"].startswith("https://go.похудение-это-есть.рф/i/E")

    with Session(engine) as session:
        account = session.scalar(select(CrmMessengerAccount).where(
            CrmMessengerAccount.platform == "max", CrmMessengerAccount.platform_user_id == "901"
        ))
        assert account is not None
        assert account.main_scenario_seen_at is None
        assert account.source == "max_bot"
        assert session.scalar(select(CrmAttributionEvent.event_type).where(
            CrmAttributionEvent.user_id == account.user_id
        )) == "max_start"
        access = session.scalar(select(MessengerLinkToken).where(MessengerLinkToken.user_id == account.user_id))
        assert access is not None
        assert access.platform == "max"
        tracking = session.scalar(select(TrackingEvent).where(TrackingEvent.user_id == account.user_id))
        assert tracking.event_type == "start_first"
        metadata = dict(tracking.metadata_json)
        token_id = metadata.pop("max_intensive_token_id")
        assert str(uuid.UUID(token_id)) == token_id
        assert metadata == {
            "messenger": "max",
            "payload_status": "empty",
            "raw_query": {},
            "max_delivery_status": "sent",
            "max_message_id": "1",
        }
    app.dependency_overrides.clear()


def test_max_account_link_issues_short_password(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    raw_token = "Mmax-account-token"
    target_user_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.execute(text("CREATE TABLE user_emails (user_id TEXT, email_normalized TEXT, is_primary BOOLEAN, created_at DATETIME)"))
        session.execute(text("CREATE TABLE user_accesses (user_id TEXT)"))
        session.execute(text("CREATE TABLE payments (user_id TEXT)"))
        session.add(CrmUser(id=target_user_id, status="active", data_origin="native"))
        session.flush()
        session.execute(
            text("INSERT INTO user_emails VALUES (:user_id, 'member@example.test', 1, CURRENT_TIMESTAMP)"),
            {"user_id": target_user_id},
        )
        session.add(
            MessengerLinkToken(
                user_id=target_user_id,
                platform="max",
                purpose="account_credentials",
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        session.commit()

    response = client.post(
        "/bot/max/webhook",
        json=max_start(payload=raw_token),
        headers={"X-Max-Bot-Api-Secret": "test-secret"},
    )
    assert response.json() == {"ok": True, "account_credentials": True}
    assert len(fake.sent) == 1
    message = fake.sent[0][1]
    match = re.search(r"Пароль: <code>([A-Za-z0-9]{8})</code>", message)
    assert match is not None
    assert not set(match.group(1)) & set("O0Il1")
    assert "member@example.test" in message
    assert "https://go.похудение-это-есть.рф/lk" in message
    with Session(engine) as session:
        credential = session.get(AccountCredential, target_user_id)
        assert credential is not None
        assert credential.issued_via == "max"
    app.dependency_overrides.clear()


def test_max_account_link_rejects_second_messenger_after_telegram_claim(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    raw_token = "Mmax-already-claimed"
    target_user_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.execute(text("CREATE TABLE user_emails (user_id TEXT, email_normalized TEXT, is_primary BOOLEAN, created_at DATETIME)"))
        session.execute(text("CREATE TABLE user_accesses (user_id TEXT)"))
        session.execute(text("CREATE TABLE payments (user_id TEXT)"))
        session.add(CrmUser(id=target_user_id, status="active", data_origin="native"))
        onboarding = AccountOnboarding(
            user_id=target_user_id,
            payment_id=str(uuid.uuid4()),
            claim_bundle_encrypted="test-bundle",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            status="claimed",
            claimed_platform="telegram",
            claimed_at=datetime.now(UTC),
        )
        session.add(onboarding)
        session.flush()
        session.add(
            MessengerLinkToken(
                user_id=target_user_id,
                account_onboarding_id=onboarding.id,
                platform="max",
                purpose="account_credentials",
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        session.commit()

    response = client.post(
        "/bot/max/webhook",
        json=max_start(payload=raw_token),
        headers={"X-Max-Bot-Api-Secret": "test-secret"},
    )

    assert response.json() == {"ok": True, "account_credentials": True}
    assert len(fake.sent) == 1
    assert "уже выданы" in fake.sent[0][1]
    with Session(engine) as session:
        assert session.get(AccountCredential, target_user_id) is None
    app.dependency_overrides.clear()


def test_max_start_uses_existing_link_catalog_once(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    admin_headers = {"X-Max-Bot-Api-Secret": "test-secret"}
    tags = client.get("/bot-api/tags").json()
    pikabu = next(tag for tag in tags if tag["name"] == "Пикабу")
    created = client.post("/bot-api/link-rules", json={"name": "MAX Пикабу", "tag_ids": [pikabu["id"]]}).json()
    alias_token = created["aliases"][0]["token"]
    redirect = client.get(
        f"/go/{alias_token}?to=max&utm_source=yandex&yclid=max-click-901",
        follow_redirects=False,
    )
    payload = parse_qs(urlparse(redirect.headers["location"]).query)["start"][0]
    response = client.post("/bot/max/webhook", json=max_start(payload=payload), headers=admin_headers)
    assert response.status_code == 200
    assert len(fake.sent) == 1

    with Session(engine) as session:
        account = session.scalar(select(CrmMessengerAccount).where(CrmMessengerAccount.platform_user_id == "901"))
        assert session.scalar(select(func.count(CrmUserTag.id)).where(CrmUserTag.user_id == account.user_id)) == 1
        events = list(session.scalars(select(CrmAttributionEvent.event_type).where(
            CrmAttributionEvent.user_id == account.user_id
        ).order_by(CrmAttributionEvent.created_at)))
        assert events == ["max_first_touch", "max_start"]
        tracking = session.scalar(select(TrackingEvent).where(
            TrackingEvent.user_id == account.user_id,
            TrackingEvent.event_type == "start_first",
        ))
        assert tracking.metadata_json["messenger"] == "max"
        assert tracking.metadata_json["raw_query"] == {
            "utm_source": "yandex",
            "yclid": "max-click-901",
        }
    app.dependency_overrides.clear()


def test_max_delivery_failure_persists_same_link_for_webhook_retry(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}
    original_send = fake.send_html

    failed_call = {}

    def fail_send(*args, **kwargs):
        failed_call["button_url"] = kwargs["button_url"]
        raise httpx.HTTPError("MAX unavailable")

    fake.send_html = fail_send
    try:
        client.post("/bot/max/webhook", json=max_start(), headers=headers)
        raise AssertionError("delivery error was not raised")
    except httpx.HTTPError:
        pass

    with Session(engine) as session:
        assert session.scalar(select(func.count(UpdateReceipt.update_id))) == 1
        assert session.scalar(select(func.count(CrmUser.id))) == 1
        assert session.scalar(select(func.count(CrmMessengerAccount.id))) == 1
        assert session.scalar(select(func.count(CrmAttributionEvent.id))) == 1
        assert session.scalar(select(func.count(TrackingEvent.id))) == 1
        assert session.scalar(select(func.count(MessengerLinkToken.id))) == 1
        tracking = session.scalar(select(TrackingEvent))
        assert tracking.metadata_json["max_delivery_status"] == "pending"

    fake.send_html = original_send
    response = client.post("/bot/max/webhook", json=max_start(), headers=headers)
    assert response.json() == {"ok": True, "retried": True}
    assert len(fake.sent) == 1
    assert fake.sent[0][2]["button_url"] == failed_call["button_url"]
    assert client.post("/bot/max/webhook", json=max_start(), headers=headers).json() == {
        "ok": True,
        "duplicate": True,
    }
    assert len(fake.sent) == 1
    app.dependency_overrides.clear()


def test_retry_does_not_resend_link_consumed_after_lost_max_response(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}

    def response_lost(*_args, **_kwargs):
        raise httpx.ReadTimeout("MAX response lost")

    fake.send_html = response_lost
    try:
        client.post("/bot/max/webhook", json=max_start(), headers=headers)
        raise AssertionError("delivery error was not raised")
    except httpx.ReadTimeout:
        pass

    with Session(engine) as session:
        token = session.scalar(select(MessengerLinkToken))
        token.consumed_at = datetime.now(UTC)
        session.commit()

    response = client.post("/bot/max/webhook", json=max_start(), headers=headers)
    assert response.json() == {"ok": True, "duplicate": True}
    assert fake.sent == []
    with Session(engine) as session:
        tracking = session.scalar(select(TrackingEvent))
        assert tracking.metadata_json["max_delivery_status"] == "sent"
        assert tracking.metadata_json["max_delivery_confirmed_by"] == "token_consumed"
    app.dependency_overrides.clear()


def test_unknown_max_payload_keeps_identity_without_inventing_attribution(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}

    response = client.post("/bot/max/webhook", json=max_start(payload="obsolete-link"), headers=headers)
    assert response.json() == {"ok": True, "intensive": True, "first_start": True}
    assert fake.sent[0][2]["button_url"].startswith("https://go.похудение-это-есть.рф/i/E")

    with Session(engine) as session:
        account = session.scalar(select(CrmMessengerAccount).where(CrmMessengerAccount.platform_user_id == "901"))
        assert account is not None
        assert session.scalar(select(func.count(CrmUserTag.id)).where(CrmUserTag.user_id == account.user_id)) == 0
        events = list(session.scalars(select(CrmAttributionEvent.event_type).where(
            CrmAttributionEvent.user_id == account.user_id
        )))
        assert events == ["max_start_unknown"]
    app.dependency_overrides.clear()


def test_max_webhook_rejects_missing_or_bad_secret(tmp_path, monkeypatch):
    client, _, _ = make_client(tmp_path, monkeypatch)
    assert client.post("/bot/max/webhook", json=max_start()).status_code == 403
    assert client.post("/bot/max/webhook", json=max_start(), headers={"X-Max-Bot-Api-Secret": "wrong"}).status_code == 403
    assert client.post("/bot/max/webhook", json={"update_type": "message_created"}, headers={"X-Max-Bot-Api-Secret": "test-secret"}).json() == {"ok": True, "ignored": True}
    app.dependency_overrides.clear()


def test_distinct_later_max_start_is_recorded_as_repeat(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}

    assert client.post("/bot/max/webhook", json=max_start(), headers=headers).status_code == 200
    assert client.post(
        "/bot/max/webhook",
        json=max_start(timestamp="2026-08-27T11:00:00Z"),
        headers=headers,
    ).status_code == 200

    with Session(engine) as session:
        events = list(session.scalars(select(TrackingEvent.event_type).order_by(
            TrackingEvent.occurred_at,
            TrackingEvent.id,
        )))
        assert events == ["start_first", "start_repeat"]
    assert len(fake.sent) == 2
    assert all(message[2]["button_text"] == "Открыть первый день" for message in fake.sent)
    assert all(message[2]["button_url"].startswith("https://go.похудение-это-есть.рф/i/E") for message in fake.sent)
    app.dependency_overrides.clear()
