from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.main as main_module
from app.database import Base, get_db, make_engine
from app.main import app
from app.models import CrmAttributionEvent, CrmMessengerAccount, CrmTag, CrmUserTag
from app.seed import seed_defaults


class FakeMax:
    def __init__(self):
        self.sent = []

    def send_html(self, user_id, text):
        self.sent.append((user_id, text))
        return "1"


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
    return TestClient(app), engine, fake


def test_max_start_saves_identity_and_stops_at_maintenance(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    headers = {"X-Max-Bot-Api-Secret": "test-secret"}
    response = client.post("/bot/max/webhook", json=max_start(), headers=headers)
    assert response.json() == {"ok": True, "maintenance": True, "first_start": True}
    assert client.post("/bot/max/webhook", json=max_start(), headers=headers).json() == {"ok": True, "duplicate": True}
    assert len(fake.sent) == 1
    assert fake.sent[0][0] == "901"
    assert "небольшом ремонте" in fake.sent[0][1]

    with Session(engine) as session:
        account = session.scalar(select(CrmMessengerAccount).where(
            CrmMessengerAccount.platform == "max", CrmMessengerAccount.platform_user_id == "901"
        ))
        assert account is not None
        assert account.main_scenario_seen_at is None
        assert account.source == "max_bot"
        assert session.scalar(select(CrmAttributionEvent.event_type).where(
            CrmAttributionEvent.user_id == account.user_id
        )) == "max_start_maintenance"
    app.dependency_overrides.clear()


def test_max_start_uses_existing_link_catalog_once(tmp_path, monkeypatch):
    client, engine, fake = make_client(tmp_path, monkeypatch)
    admin_headers = {"X-Max-Bot-Api-Secret": "test-secret"}
    tags = client.get("/bot-api/tags").json()
    pikabu = next(tag for tag in tags if tag["name"] == "Пикабу")
    created = client.post("/bot-api/link-rules", json={"name": "MAX Пикабу", "tag_ids": [pikabu["id"]]}).json()
    payload = created["aliases"][0]["token"]
    response = client.post("/bot/max/webhook", json=max_start(payload=payload), headers=admin_headers)
    assert response.status_code == 200
    assert len(fake.sent) == 1

    with Session(engine) as session:
        account = session.scalar(select(CrmMessengerAccount).where(CrmMessengerAccount.platform_user_id == "901"))
        assert session.scalar(select(func.count(CrmUserTag.id)).where(CrmUserTag.user_id == account.user_id)) == 1
        events = list(session.scalars(select(CrmAttributionEvent.event_type).where(
            CrmAttributionEvent.user_id == account.user_id
        ).order_by(CrmAttributionEvent.created_at)))
        assert events == ["max_first_touch", "max_start_maintenance"]
    app.dependency_overrides.clear()


def test_max_webhook_rejects_missing_or_bad_secret(tmp_path, monkeypatch):
    client, _, _ = make_client(tmp_path, monkeypatch)
    assert client.post("/bot/max/webhook", json=max_start()).status_code == 403
    assert client.post("/bot/max/webhook", json=max_start(), headers={"X-Max-Bot-Api-Secret": "wrong"}).status_code == 403
    assert client.post("/bot/max/webhook", json={"update_type": "message_created"}, headers={"X-Max-Bot-Api-Secret": "test-secret"}).json() == {"ok": True, "ignored": True}
    app.dependency_overrides.clear()
