from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.main as main_module
from app.database import Base, get_db, make_engine
from app.main import app
from app.models import Contact, CrmMessengerAccount, CrmTag, CrmUserTag, SequenceRun, TrackingEvent, TrackingLinkAlias
from app.seed import seed_defaults


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send_content(self, chat_id, content, configuration):
        self.sent.append((chat_id, getattr(content, "code", None) or content.body_source))
        return str(len(self.sent))


def make_client(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'tracking.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        session.add(CrmTag(code="pikabu", name="Пикабу", category="source", status="active"))
        session.add(CrmTag(code="post_speed", name="Пост - Скорость похудения", category="content", status="active"))
        session.commit()

    def db_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module, "client", lambda: FakeTelegram())
    monkeypatch.setattr(main_module.settings, "admin_username", "")
    monkeypatch.setattr(main_module.settings, "admin_password", "")
    monkeypatch.setattr(main_module.settings, "telegram_test_bot_username", "TetrisgfgfgfBot")
    monkeypatch.setattr(main_module.settings, "telegram_public_base_url", "https://go.example.test")
    return TestClient(app), engine


def start_update(update_id: int, telegram_id: int, payload: str = "") -> dict:
    text = "/start" + (f" {payload}" if payload else "")
    return {"update_id": update_id, "message": {"from": {"id": telegram_id, "first_name": "Test"}, "chat": {"id": telegram_id}, "text": text}}


def test_first_touch_assigns_tags_once_and_unknown_code_is_safe(tmp_path, monkeypatch):
    client, engine = make_client(tmp_path, monkeypatch)
    tags = client.get("/bot-api/tags").json()
    pikabu = next(tag for tag in tags if tag["name"] == "Пикабу")
    created = client.post("/bot-api/link-rules", json={"name": "Главная Пикабу", "tag_ids": [pikabu["id"]]}).json()
    token = created["aliases"][0]["token"]

    assert client.post("/telegram/webhook", json=start_update(1, 501, token)).status_code == 200
    assert client.post("/telegram/webhook", json=start_update(2, 501, token)).status_code == 200
    assert client.post("/telegram/webhook", json=start_update(3, 502, "unknown-old-code")).status_code == 200

    with Session(engine) as session:
        first_account = session.scalar(select(CrmMessengerAccount).where(CrmMessengerAccount.platform_user_id == "501"))
        second_account = session.scalar(select(CrmMessengerAccount).where(CrmMessengerAccount.platform_user_id == "502"))
        assert session.scalar(select(func.count(CrmUserTag.id)).where(CrmUserTag.user_id == first_account.user_id)) == 1
        assert session.scalar(select(func.count(CrmUserTag.id)).where(CrmUserTag.user_id == second_account.user_id)) == 0
        event_types = list(session.scalars(select(TrackingEvent.event_type).where(TrackingEvent.telegram_user_id == "501").order_by(TrackingEvent.occurred_at)))
        assert event_types == ["start_first", "start_repeat"]
        assert session.scalar(select(TrackingEvent.event_type).where(TrackingEvent.telegram_user_id == "502")) == "start_unknown"
    app.dependency_overrides.clear()


def test_maintenance_preserves_first_touch_without_marking_welcome_seen(tmp_path, monkeypatch):
    client, engine = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_mode", True)
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_allowed_user_ids", "42")
    pikabu = next(tag for tag in client.get("/bot-api/tags").json() if tag["name"] == "Пикабу")
    created = client.post("/bot-api/link-rules", json={"name": "Пикабу во время ремонта", "tag_ids": [pikabu["id"]]}).json()
    token = created["aliases"][0]["token"]

    assert client.post("/telegram/webhook", json=start_update(4, 503, token)).json() == {"ok": True, "maintenance": True}

    with Session(engine) as session:
        account = session.scalar(select(CrmMessengerAccount).where(CrmMessengerAccount.platform_user_id == "503"))
        contact = session.scalar(select(Contact).where(Contact.telegram_user_id == "503"))
        assert account.main_scenario_seen_at is None
        assert contact.first_source_token == token
        assert session.scalar(select(func.count(CrmUserTag.id)).where(CrmUserTag.user_id == account.user_id)) == 1
        assert session.scalar(select(func.count(SequenceRun.id)).where(SequenceRun.contact_id == contact.id)) == 0
        maintenance = session.scalar(select(TrackingEvent).where(TrackingEvent.contact_id == contact.id, TrackingEvent.event_type == "maintenance_contact"))
        assert maintenance.metadata_json["has_masterclass"] is False
        assert maintenance.metadata_json["tracking_link_id"] == created["id"]
        start_maintenance = session.scalar(select(TrackingEvent).where(
            TrackingEvent.contact_id == contact.id,
            TrackingEvent.event_type == "start_maintenance",
        ))
        assert start_maintenance.metadata_json["is_first_bot_visit"] is True

    assert client.post("/telegram/webhook", json=start_update(5, 503, token)).json() == {
        "ok": True,
        "maintenance": True,
    }
    with Session(engine) as session:
        maintenance_starts = session.scalars(select(TrackingEvent).where(
            TrackingEvent.telegram_user_id == "503",
            TrackingEvent.event_type == "start_maintenance",
        )).all()
        assert len(maintenance_starts) == 2
        assert sum(
            event.metadata_json["is_first_bot_visit"] is True
            for event in maintenance_starts
        ) == 1

    monkeypatch.setattr(main_module.settings, "telegram_maintenance_mode", False)
    assert client.post("/telegram/webhook", json=start_update(6, 503)).json() == {"ok": True}
    with Session(engine) as session:
        account = session.scalar(select(CrmMessengerAccount).where(CrmMessengerAccount.platform_user_id == "503"))
        contact = session.scalar(select(Contact).where(Contact.telegram_user_id == "503"))
        assert account.main_scenario_seen_at is not None
        assert session.scalar(select(func.count(CrmUserTag.id)).where(CrmUserTag.user_id == account.user_id)) == 1
        assert session.scalar(select(func.count(SequenceRun.id)).where(SequenceRun.contact_id == contact.id)) == 1

    graph = client.get("/bot-api/map?module_code=start_attribution").json()
    positions = {node["id"]: node["position"] for node in graph["nodes"]}
    assert positions["attribution"] < positions["purchase_fact"] < positions["maintenance_gate"] < positions["has_masterclass"]
    complete = next(node for node in graph["nodes"] if node["id"] == "send_complete")
    assert complete["label"] == "Отправить оглавление завершённого интенсива"
    app.dependency_overrides.clear()


def test_go_utm_session_uses_only_saved_exact_mapping_and_v_is_web_only(tmp_path, monkeypatch):
    client, engine = make_client(tmp_path, monkeypatch)
    tags = client.get("/bot-api/tags").json()
    post_tag = next(tag for tag in tags if tag["name"] == "Пост - Скорость похудения")
    created = client.post("/bot-api/link-rules", json={"name": "Статья про скорость"}).json()
    token = created["aliases"][0]["token"]
    client.post("/bot-api/utm/rules", json={"parameter_name": "utm_content", "raw_value": "speed", "tag_id": post_tag["id"]})

    redirect = client.get(
        f"/go/{token}?utm_content=speed&utm_source=raw-source&YCLID=123456789&gclid=discard-me",
        follow_redirects=False,
    )
    assert redirect.status_code == 307
    payload = parse_qs(urlparse(redirect.headers["location"]).query)["start"][0]
    assert payload.startswith("U")
    assert client.post("/telegram/webhook", json=start_update(10, 601, payload)).status_code == 200
    warning = client.get(f"/go/{token}V", follow_redirects=False)
    assert warning.status_code == 200
    assert "Перед переходом в Telegram" in warning.text
    assert client.post("/telegram/webhook", json=start_update(11, 602, f"{token}V")).status_code == 200

    with Session(engine) as session:
        mapped = session.scalar(select(CrmMessengerAccount).where(CrmMessengerAccount.platform_user_id == "601"))
        direct_v = session.scalar(select(CrmMessengerAccount).where(CrmMessengerAccount.platform_user_id == "602"))
        mapped_names = list(session.scalars(select(CrmTag.name).join(CrmUserTag, CrmUserTag.tag_id == CrmTag.id).where(CrmUserTag.user_id == mapped.user_id)))
        assert mapped_names == ["Пост - Скорость похудения"]
        web_click = session.scalar(select(TrackingEvent).where(TrackingEvent.tracking_link_id == created["id"], TrackingEvent.event_type == "web_click"))
        start = session.scalar(select(TrackingEvent).where(TrackingEvent.telegram_user_id == "601", TrackingEvent.event_type == "start_first"))
        expected_query = {"utm_content": "speed", "utm_source": "raw-source", "yclid": "123456789"}
        assert web_click.metadata_json["raw_query"] == expected_query
        assert start.metadata_json["raw_query"] == expected_query
        assert session.scalar(select(func.count(CrmUserTag.id)).where(CrmUserTag.user_id == direct_v.user_id)) == 0
        assert session.scalar(select(TrackingEvent.event_type).where(TrackingEvent.telegram_user_id == "602")) == "start_unknown"
    app.dependency_overrides.clear()


def test_go_preserves_yclid_without_utm_parameters(tmp_path, monkeypatch):
    client, engine = make_client(tmp_path, monkeypatch)
    created = client.post("/bot-api/link-rules", json={"name": "Яндекс без UTM"}).json()
    token = created["aliases"][0]["token"]

    redirect = client.get(f"/go/{token}?yclid=987654321", follow_redirects=False)
    payload = parse_qs(urlparse(redirect.headers["location"]).query)["start"][0]

    assert payload.startswith("U")
    assert client.post("/telegram/webhook", json=start_update(12, 603, payload)).status_code == 200
    assert client.post("/telegram/webhook", json=start_update(13, 604, payload)).status_code == 200
    with Session(engine) as session:
        start = session.scalar(
            select(TrackingEvent).where(
                TrackingEvent.telegram_user_id == "603",
                TrackingEvent.event_type == "start_first",
            )
        )
        assert start.metadata_json["raw_query"] == {"yclid": "987654321"}
        replay = session.scalar(
            select(TrackingEvent).where(TrackingEvent.telegram_user_id == "604")
        )
        assert replay.event_type == "start_expired_session"
        assert replay.metadata_json["raw_query"] == {}
    app.dependency_overrides.clear()


def test_go_can_open_max_with_same_one_time_attribution_payload(tmp_path, monkeypatch):
    client, engine = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module.settings, "max_bot_username", "id230409966750_bot")
    created = client.post("/bot-api/link-rules", json={"name": "Яндекс → MAX"}).json()
    token = created["aliases"][0]["token"]

    redirect = client.get(
        f"/go/{token}?to=max&utm_source=yandex&yclid=max-click-1",
        follow_redirects=False,
    )

    assert redirect.status_code == 307
    parsed = urlparse(redirect.headers["location"])
    assert parsed.netloc == "max.ru"
    assert parsed.path == "/id230409966750_bot"
    payload = parse_qs(parsed.query)["start"][0]
    assert payload.startswith("U")
    with Session(engine) as session:
        click = session.scalar(select(TrackingEvent).where(TrackingEvent.event_type == "web_click"))
        assert click.metadata_json["raw_query"] == {
            "utm_source": "yandex",
            "yclid": "max-click-1",
        }
    app.dependency_overrides.clear()


def test_channel_invite_touch_is_claimed_on_first_bot_start(tmp_path, monkeypatch):
    client, engine = make_client(tmp_path, monkeypatch)
    pikabu = next(tag for tag in client.get("/bot-api/tags").json() if tag["name"] == "Пикабу")
    created = client.post("/bot-api/link-rules", json={"name": "Пикабу → канал", "target_kind": "channel_invite", "tag_ids": [pikabu["id"]]}).json()
    alias_id = created["aliases"][0]["id"]
    invite_url = "https://t.me/+testInvite"
    with Session(engine) as session:
        alias = session.get(TrackingLinkAlias, alias_id)
        alias.telegram_invite_url = invite_url
        alias.telegram_chat_id = "@Fitness_Talks"
        session.commit()
    joined = {"update_id": 20, "chat_member": {"from": {"id": 1}, "chat": {"id": -1001}, "new_chat_member": {"status": "member", "user": {"id": 701, "first_name": "Channel"}}, "invite_link": {"invite_link": invite_url}}}
    assert client.post("/telegram/webhook", json=joined).status_code == 200
    assert client.post("/telegram/webhook", json=start_update(21, 701)).status_code == 200

    with Session(engine) as session:
        account = session.scalar(select(CrmMessengerAccount).where(CrmMessengerAccount.platform_user_id == "701"))
        names = list(session.scalars(select(CrmTag.name).join(CrmUserTag, CrmUserTag.tag_id == CrmTag.id).where(CrmUserTag.user_id == account.user_id)))
        assert names == ["Пикабу"]
        join = session.scalar(select(TrackingEvent).where(TrackingEvent.event_type == "channel_join"))
        assert join.processed_at is not None
        start = session.scalar(select(TrackingEvent).where(TrackingEvent.telegram_user_id == "701", TrackingEvent.event_type == "start_first"))
        assert start.tracking_link_id == join.tracking_link_id
    app.dependency_overrides.clear()
