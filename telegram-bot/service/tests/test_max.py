import json
import hashlib
import re
import ssl
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import pytest
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
    ContentItem,
    CrmAttributionEvent,
    CrmMessengerAccount,
    CrmTag,
    CrmUser,
    CrmUserTag,
    Contact,
    MessengerLinkToken,
    TrackingEvent,
    UpdateReceipt,
    SequenceRun,
)
from app.seed import seed_defaults


class FakeMax:
    def __init__(self):
        self.sent = []

    def send_html(self, user_id, text, **kwargs):
        self.sent.append((user_id, text, kwargs))
        return "1"

    def send_content(self, user_id, content, configuration):
        self.sent.append((user_id, content.body_source or "", configuration))
        return str(len(self.sent))

    def subscription_status(self, _user_id):
        return None


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


def test_max_client_sends_sequence_photo_and_link_button():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"message": {"body": {"mid": "max-sequence-1"}}})

    content = SimpleNamespace(
        body_source="<b>Напоминание</b>",
        media_kind="photo",
        media_path="https://cdn.example.test/reminder.jpg",
    )
    message_id = MaxClient("max-secret", httpx.MockTransport(handler)).send_content(
        "901",
        content,
        {"buttons": [{"text": "Открыть часть #1", "url": "https://example.test/i/Ecode"}]},
    )

    assert message_id == "max-sequence-1"
    payload = json.loads(captured["request"].content)
    assert payload["text"] == "<b>Напоминание</b>"
    assert payload["attachments"][0] == {
        "type": "image",
        "payload": {"url": "https://cdn.example.test/reminder.jpg"},
    }
    assert payload["attachments"][1]["type"] == "inline_keyboard"


def test_max_upload_uses_video_token_returned_before_file_upload(tmp_path):
    video = tmp_path / "intro.mp4"
    video.write_bytes(b"video")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/uploads":
            return httpx.Response(200, json={
                "url": "https://upload.example.test/video",
                "token": "video-token",
            })
        if request.url.host == "upload.example.test":
            return httpx.Response(200, json={"retval": 1})
        return httpx.Response(200, json={"message": {"body": {"mid": "max-video-1"}}})

    content = SimpleNamespace(
        body_source="",
        media_kind="video_note",
        media_path=str(video),
    )
    message_id = MaxClient("max-secret", httpx.MockTransport(handler)).send_content(
        "901", content, {},
    )

    assert message_id == "max-video-1"
    payload = json.loads(requests[-1].content)
    assert payload["attachments"] == [{
        "type": "video",
        "payload": {"retval": 1, "token": "video-token"},
    }]


def test_max_html_compaction_keeps_visible_text_and_respects_limit():
    source = "<b>" + ("x" * 3994) + "</b>"
    result = MaxClient._compact_html(source)

    assert result == "x" * 3994
    assert len(result) <= 4000


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
    assert len(fake.sent) == 2
    assert fake.sent[0][0] == "901"
    assert fake.sent[0][1] == ""
    assert "Бесплатный интенсив" in fake.sent[1][1]
    assert fake.sent[1][2]["buttons"][0]["text"] == "Открыть интенсив"
    assert fake.sent[1][2]["buttons"][0]["url"].startswith("https://go.похудение-это-есть.рф/i/E")

    with Session(engine) as session:
        account = session.scalar(select(CrmMessengerAccount).where(
            CrmMessengerAccount.platform == "max", CrmMessengerAccount.platform_user_id == "901"
        ))
        assert account is not None
        assert account.main_scenario_seen_at is not None
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
            "max_message_id": "2",
            "max_start_decision": "launch_welcome",
            "is_first_scenario": True,
        }
        contact = session.scalar(select(Contact).where(Contact.user_id == account.user_id))
        assert contact is not None
        run = session.scalar(select(SequenceRun).where(SequenceRun.contact_id == contact.id))
        assert run is not None
        assert run.status == "active"
        assert run.current_step_key == "welcome_reminder_check_day1"
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


@pytest.mark.parametrize(
    ("payload", "day_number", "body_marker", "expects_personal_link"),
    [
        ("iz1", 1, "Просто кладите ложку на стол", False),
        ("iz2", 2, "Правило 30-ти растений", True),
        ("iz3", 3, "Сколько времени нужно на похудение", True),
    ],
)
def test_max_assignment_route_sends_approved_post_without_an_extra_web_hop(
    tmp_path,
    monkeypatch,
    payload,
    day_number,
    body_marker,
    expects_personal_link,
):
    client, engine, fake = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/bot/max/webhook",
        json=max_start(payload=payload),
        headers={"X-Max-Bot-Api-Secret": "test-secret"},
    )

    assert response.json() == {"ok": True, "assignment_day": day_number}
    assert len(fake.sent) == 1
    assert fake.sent[0][0] == "901"
    assert "Переслано из основного Telegram-канала" in fake.sent[0][1]
    assert body_marker in fake.sent[0][1]
    assert "{{" not in fake.sent[0][1]
    assert fake.sent[0][2] == {}
    with Session(engine) as session:
        delivery = session.scalar(select(TrackingEvent).where(
            TrackingEvent.event_type == "intensive_assignment_delivery"
        ))
        assert delivery is not None
        assert delivery.metadata_json == {
            "messenger": "max",
            "assignment_day": day_number,
            "content_code": f"tpl_max_forwarded_assignment_day{day_number}",
            "max_delivery_status": "sent",
            "max_message_id": "1",
        }
        personal_link = session.scalar(select(MessengerLinkToken))
        assert (personal_link is not None) is expects_personal_link
        if personal_link is not None:
            assert personal_link.platform == "max"
            assert personal_link.purpose == "intensive_access"
    assert client.post(
        "/bot/max/webhook",
        json=max_start(payload=payload),
        headers={"X-Max-Bot-Api-Secret": "test-secret"},
    ).json() == {"ok": True, "duplicate": True}
    assert len(fake.sent) == 1
    app.dependency_overrides.clear()


def test_max_assignment_uncertain_delivery_is_not_duplicated_by_webhook_retry(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}
    original_send = fake.send_html

    accepted_calls = []

    def fail_send(*args, **kwargs):
        accepted_calls.append((args, kwargs))
        raise httpx.ReadTimeout("MAX accepted the message but the response was lost")

    fake.send_html = fail_send
    with pytest.raises(httpx.HTTPError):
        client.post("/bot/max/webhook", json=max_start(payload="iz1"), headers=headers)

    with Session(engine) as session:
        delivery = session.scalar(select(TrackingEvent).where(
            TrackingEvent.event_type == "intensive_assignment_delivery"
        ))
        assert delivery is not None
        assert delivery.metadata_json["max_delivery_kind"] == "assignment"
        assert delivery.metadata_json["max_delivery_status"] == "uncertain"
        assert delivery.metadata_json["max_delivery_error_type"] == "ReadTimeout"

    response = client.post("/bot/max/webhook", json=max_start(payload="iz1"), headers=headers)
    assert response.json() == {
        "ok": True,
        "duplicate": True,
        "delivery_status": "uncertain",
        "assignment_day": 1,
    }
    assert fake.sent == []
    assert len(accepted_calls) == 1

    with Session(engine) as session:
        delivery = session.scalar(select(TrackingEvent).where(
            TrackingEvent.event_type == "intensive_assignment_delivery"
        ))
        assert delivery.metadata_json["max_delivery_status"] == "uncertain"

    fake.send_html = original_send
    second_click = max_start(timestamp="2026-08-27T10:01:00Z", payload="iz1")
    assert client.post("/bot/max/webhook", json=second_click, headers=headers).json() == {
        "ok": True,
        "assignment_day": 1,
    }
    assert len(fake.sent) == 1
    assert "Просто кладите ложку на стол" in fake.sent[0][1]
    assert client.post(
        "/bot/max/webhook",
        json=second_click,
        headers=headers,
    ).json() == {"ok": True, "duplicate": True}
    assert len(fake.sent) == 1
    app.dependency_overrides.clear()


def test_max_assignment_retries_after_connect_failure(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}
    original_send = fake.send_html

    def fail_before_request(*_args, **_kwargs):
        raise httpx.ConnectError("MAX connection unavailable")

    fake.send_html = fail_before_request
    with pytest.raises(httpx.ConnectError):
        client.post("/bot/max/webhook", json=max_start(payload="iz1"), headers=headers)

    with Session(engine) as session:
        delivery = session.scalar(select(TrackingEvent).where(
            TrackingEvent.event_type == "intensive_assignment_delivery"
        ))
        assert delivery.metadata_json["max_delivery_status"] == "retryable"
        assert delivery.metadata_json["max_delivery_error_type"] == "ConnectError"

    fake.send_html = original_send
    assert client.post(
        "/bot/max/webhook",
        json=max_start(payload="iz1"),
        headers=headers,
    ).json() == {"ok": True, "retried": True, "assignment_day": 1}
    assert len(fake.sent) == 1
    assert "Просто кладите ложку на стол" in fake.sent[0][1]
    app.dependency_overrides.clear()


def test_max_assignment_does_not_retry_after_ambiguous_server_error(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}
    request = httpx.Request("POST", "https://platform-api2.max.ru/messages")
    response = httpx.Response(503, request=request)

    def fail_after_server_received_request(*_args, **_kwargs):
        raise httpx.HTTPStatusError("MAX internal error", request=request, response=response)

    fake.send_html = fail_after_server_received_request
    with pytest.raises(httpx.HTTPStatusError):
        client.post("/bot/max/webhook", json=max_start(payload="iz1"), headers=headers)

    with Session(engine) as session:
        delivery = session.scalar(select(TrackingEvent).where(
            TrackingEvent.event_type == "intensive_assignment_delivery"
        ))
        assert delivery.metadata_json["max_delivery_status"] == "uncertain"

    result = client.post(
        "/bot/max/webhook",
        json=max_start(payload="iz1"),
        headers=headers,
    ).json()
    assert result == {
        "ok": True,
        "duplicate": True,
        "delivery_status": "uncertain",
        "assignment_day": 1,
    }
    app.dependency_overrides.clear()


def test_max_assignment_refuses_unapproved_content(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    with Session(engine) as session:
        item = session.scalar(select(ContentItem).where(
            ContentItem.code == "tpl_max_forwarded_assignment_day1"
        ))
        item.editorial_status = "draft"
        session.commit()

    with pytest.raises(RuntimeError, match="MAX assignment content is unavailable"):
        client.post(
            "/bot/max/webhook",
            json=max_start(payload="iz1"),
            headers={"X-Max-Bot-Api-Secret": "test-secret"},
        )
    assert fake.sent == []
    app.dependency_overrides.clear()


def test_max_assignment_refuses_oversized_approved_runtime_content(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    with Session(engine) as session:
        item = session.scalar(select(ContentItem).where(
            ContentItem.code == "tpl_max_forwarded_assignment_day1"
        ))
        item.body_source = "x" * 4001
        session.commit()

    with pytest.raises(RuntimeError, match="MAX assignment exceeds 4000 characters"):
        client.post(
            "/bot/max/webhook",
            json=max_start(payload="iz1"),
            headers={"X-Max-Bot-Api-Secret": "test-secret"},
        )
    assert fake.sent == []
    app.dependency_overrides.clear()


def test_max_assignment_retries_after_rate_limit_response(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}
    original_send = fake.send_html
    request = httpx.Request("POST", "https://platform-api2.max.ru/messages")
    response = httpx.Response(429, request=request)

    def rate_limited(*_args, **_kwargs):
        raise httpx.HTTPStatusError("MAX rate limit", request=request, response=response)

    fake.send_html = rate_limited
    with pytest.raises(httpx.HTTPStatusError):
        client.post("/bot/max/webhook", json=max_start(payload="iz1"), headers=headers)

    fake.send_html = original_send
    assert client.post(
        "/bot/max/webhook",
        json=max_start(payload="iz1"),
        headers=headers,
    ).json() == {"ok": True, "retried": True, "assignment_day": 1}
    assert len(fake.sent) == 1
    with Session(engine) as session:
        delivery = session.scalar(select(TrackingEvent).where(
            TrackingEvent.event_type == "intensive_assignment_delivery"
        ))
        assert delivery.metadata_json["max_delivery_status"] == "sent"
    app.dependency_overrides.clear()


def test_max_assignment_does_not_retry_after_terminal_client_response(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}
    request = httpx.Request("POST", "https://platform-api2.max.ru/messages")
    response = httpx.Response(400, request=request)

    def rejected(*_args, **_kwargs):
        raise httpx.HTTPStatusError("MAX rejected message", request=request, response=response)

    fake.send_html = rejected
    with pytest.raises(httpx.HTTPStatusError):
        client.post("/bot/max/webhook", json=max_start(payload="iz1"), headers=headers)

    assert client.post(
        "/bot/max/webhook",
        json=max_start(payload="iz1"),
        headers=headers,
    ).json() == {
        "ok": True,
        "duplicate": True,
        "delivery_status": "failed",
        "assignment_day": 1,
    }
    assert fake.sent == []
    with Session(engine) as session:
        delivery = session.scalar(select(TrackingEvent).where(
            TrackingEvent.event_type == "intensive_assignment_delivery"
        ))
        assert delivery.metadata_json["max_delivery_status"] == "failed"
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
    assert len(fake.sent) == 2

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
    original_send = fake.send_content

    def fail_send(*args, **kwargs):
        raise httpx.HTTPError("MAX unavailable")

    fake.send_content = fail_send
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

    fake.send_content = original_send
    response = client.post("/bot/max/webhook", json=max_start(), headers=headers)
    assert response.json() == {"ok": True, "retried": True}
    assert len(fake.sent) == 2
    assert fake.sent[1][2]["buttons"][0]["url"].startswith("https://go.похудение-это-есть.рф/i/E")
    assert client.post("/bot/max/webhook", json=max_start(), headers=headers).json() == {
        "ok": True,
        "duplicate": True,
    }
    assert len(fake.sent) == 2
    app.dependency_overrides.clear()


def test_retry_does_not_resend_link_consumed_after_lost_max_response(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}

    def response_lost(*_args, **_kwargs):
        raise httpx.ReadTimeout("MAX response lost")

    fake.send_content = response_lost
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
    assert fake.sent[1][2]["buttons"][0]["url"].startswith("https://go.похудение-это-есть.рф/i/E")

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
        events = list(session.scalars(select(TrackingEvent.event_type).where(
            TrackingEvent.event_type.in_(["start_first", "start_repeat"])
        ).order_by(
            TrackingEvent.occurred_at,
            TrackingEvent.id,
        )))
        assert events == ["start_first", "start_repeat"]
    assert len(fake.sent) == 3
    assert fake.sent[1][2]["buttons"][0]["text"] == "Открыть интенсив"
    assert fake.sent[1][2]["buttons"][0]["url"].startswith("https://go.похудение-это-есть.рф/i/E")
    app.dependency_overrides.clear()
