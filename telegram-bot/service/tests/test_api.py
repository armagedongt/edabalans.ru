from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import Base, get_db, make_engine
from app.main import app
import app.main as main_module
from app.models import BotInstance, Contact, ContentItem, CrmMessengerAccount, SequenceRun, StepDelivery, TrackingEvent, UpdateReceipt
from app.seed import seed_defaults


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.callbacks = []
        self.configurations = []

    def send_content(self, chat_id, content, configuration):
        self.sent.append((chat_id, content.code if hasattr(content, "code") else content.body_source))
        self.configurations.append(configuration)
        return str(len(self.sent))

    def answer_callback(self, callback_query_id, text=""):
        self.callbacks.append((callback_query_id, text))


def test_admin_login_uses_cookie_without_browser_basic_prompt(monkeypatch):
    monkeypatch.setattr(main_module.settings, "admin_username", "owner@example.com")
    monkeypatch.setattr(main_module.settings, "admin_password", "correct-password")
    client = TestClient(app, base_url="https://testserver")

    login_page = client.get("/bot")
    assert login_page.status_code == 200
    assert "Вход в админку" in login_page.text

    unauthorized = client.get("/bot-api/sequences")
    assert unauthorized.status_code == 401
    assert "www-authenticate" not in unauthorized.headers

    assert client.post("/bot-api/login", json={"username": "owner@example.com", "password": "wrong"}).status_code == 401
    logged_in = client.post("/bot-api/login", json={"username": "owner@example.com", "password": "correct-password"})
    assert logged_in.status_code == 200
    admin_page = client.get("/bot")
    assert admin_page.status_code == 200
    assert 'data-view="modules"' in admin_page.text
    assert "Карта бота" not in admin_page.text
    admin_script = client.get("/bot/app.js")
    assert admin_script.status_code == 200
    assert "Один источник логики" in admin_script.text
    assert '<svg id="flow-map"' not in admin_script.text


def test_admin_can_upload_media(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module.settings, "admin_username", "")
    monkeypatch.setattr(main_module.settings, "admin_password", "")
    monkeypatch.setattr(main_module.settings, "media_root", str(tmp_path))
    client = TestClient(app)
    response = client.post("/bot-api/media", files={"file": ("photo.jpg", b"jpeg-data", "image/jpeg")})
    assert response.status_code == 200
    assert response.json()["media_kind"] == "photo"
    assert (tmp_path / response.json()["media_path"].split("/")[-1]).read_bytes() == b"jpeg-data"


def test_webhook_start_is_idempotent_and_admin_can_inspect(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'api.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        day1 = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_day1"))
        day1.status = "published"; day1.editorial_status = "approved"
        session.commit()

    def db_override():
        with Session(engine) as session:
            yield session

    fake = FakeTelegram()
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module, "client", lambda: fake)
    monkeypatch.setattr(main_module.settings, "telegram_webhook_secret", "")
    monkeypatch.setattr(main_module.settings, "admin_username", "")
    monkeypatch.setattr(main_module.settings, "admin_password", "")
    client = TestClient(app)
    update = {"update_id": 100, "message": {"from": {"id": 42, "first_name": "Sergey", "username": "tester"}, "chat": {"id": 42}, "text": "/start"}}
    assert client.post("/telegram/webhook", json=update).json() == {"ok": True}
    assert client.post("/telegram/webhook", json=update).json()["duplicate"] is True
    assert [x[1] for x in fake.sent] == ["tpl_start_navigation_pin", "tpl_entry_circle", "tpl_start_welcome_offer"]
    contacts = client.get("/bot-api/contacts").json()
    assert len(contacts) == 1
    assert contacts[0]["run_status"] == "waiting"
    callback = {"update_id": 101, "callback_query": {"id": "cb-1", "from": {"id": 42, "first_name": "Sergey", "username": "tester"}, "message": {"chat": {"id": 42}}, "data": "start_intensive"}}
    assert client.post("/telegram/webhook", json=callback).json() == {"ok": True}
    repeat = {"update_id": 102, "message": {"from": {"id": 42, "first_name": "Sergey", "username": "tester"}, "chat": {"id": 42}, "text": "/start"}}
    assert client.post("/telegram/webhook", json=repeat).json() == {"ok": True}
    assert len(fake.sent) == 5
    assert fake.sent[-1][1] == "tpl_start_intensive_waiting"
    assert "tpl_day1" in [item[1] for item in fake.sent]
    overview = client.get("/bot-api/map").json()
    assert overview["level"] == "overview"
    assert any(node["id"] == "module:start_attribution" for node in overview["nodes"])
    sequences = client.get("/bot-api/sequences").json()
    assert [item["code"] for item in sequences[:3]] == ["start_attribution", "welcome_intensive", "prepurchase_nurture"]
    assert "prepurchase_masterclass" not in [item["code"] for item in sequences]
    module = client.get("/bot-api/map?module_code=start_attribution").json()
    assert module["level"] == "module"
    assert any(node["id"] == "exit_welcome" and node["kind"] == "module_exit" for node in module["nodes"])
    assert any(node["id"] == "exit_error" and node["kind"] == "error" for node in module["nodes"])
    assert any(edge["source"] == "welcome_run_active" and edge["target"] == "welcome_ever_started" and edge["branch"] == "false" for edge in module["edges"])
    assert any(edge["source"] == "welcome_ever_started" and edge["target"] == "exit_welcome" and edge["branch"] == "false" for edge in module["edges"])
    assert any(edge["source"] == "welcome_ever_started" and edge["target"] == "exit_error" and edge["branch"] == "true" for edge in module["edges"])
    detail = client.get("/bot-api/map?sequence_code=welcome_intensive").json()
    assert detail["level"] == "sequence"
    assert len([node for node in detail["nodes"] if node["kind"] in {"message", "video_note"}]) == 11
    offer_node = next(node for node in detail["nodes"] if node["id"] == "welcome_offer")
    assert offer_node["content"]["code"] == "tpl_start_welcome_offer"
    old_callback = offer_node["configuration"]["buttons"][0]["callback_data"]
    edited_button = client.patch(f"/bot-api/steps/{offer_node['step_id']}/presentation", json={"button_text": "Поехали"})
    assert edited_button.status_code == 200
    assert edited_button.json()["configuration"]["buttons"][0]["text"] == "Поехали"
    assert edited_button.json()["configuration"]["buttons"][0]["callback_data"] == old_callback
    assert any(edge["branch"] == "true" for edge in detail["edges"])
    postpurchase_map = client.get("/bot-api/map?module_code=postpurchase_masterclass").json()
    assert postpurchase_map["level"] == "module"
    assert any(node["id"] == "pp_review_week_day7" for node in postpurchase_map["nodes"])
    review_condition = next(node for node in postpurchase_map["nodes"] if node["id"] == "condition:pp_review_week_day7")
    assert "ACCESS_MASTERCLASS" in review_condition["details"]["Точный факт"]
    sequence_detail = client.get("/bot-api/sequences/welcome_intensive").json()
    logic_step = next(step for step in sequence_detail["steps"] if step["kind"] == "DELAY")
    assert client.patch(f"/bot-api/steps/{logic_step['id']}", json={"delay_seconds": 60}).status_code == 409
    crm_user_id = "11111111-1111-1111-1111-111111111111"
    with Session(engine) as session:
        contact = session.scalar(select(Contact))
        contact.user_id = crm_user_id
        session.commit()
        assert session.scalar(select(func.count(Contact.id))) == 1
        assert session.scalar(select(CrmMessengerAccount.main_scenario_seen_at)) is not None
        assert session.scalar(select(func.count(SequenceRun.id))) == 1
        assert session.scalar(select(func.count(StepDelivery.id))) == 4
        assert session.scalar(select(func.count(UpdateReceipt.update_id))) == 3
    state = client.get(f"/bot-api/users/{crm_user_id}").json()
    assert state["run_status"] == "active"
    assert state["sent"] in {0, 4}
    preview = client.get(f"/bot-api/contacts/{contacts[0]['id']}/start-preview").json()
    assert preview["decision"]["code"] == "intensive_waiting"
    simulated = client.post("/bot-api/start-router/simulate", json={"is_first_visit":False,"has_masterclass":True,"day_four_sent":False,"has_active_welcome_run":True,"welcome_ever_started":True}).json()
    assert simulated["decision"]["code"] == "masterclass_owned"
    sent = client.post(f"/bot-api/users/{crm_user_id}/messages", json={"text": "Проверка"}).json()
    assert sent["status"] == "sent"
    link = client.post("/bot-api/tracking-links", json={"platform":"youtube","placement":"video-1"}).json()
    redirect = client.get(f"/r/{link['token']}", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"].endswith(f"?start={link['token']}")
    stats = client.get("/bot-api/tracking-links").json()
    assert stats[0]["clicks"] == 1
    assert stats[0]["starts"] == 0
    assert "YouTube" in client.get("/bot-api/tracking-platforms").json()
    app.dependency_overrides.clear()


def test_maintenance_mode_waitlists_outsider_and_allows_owner(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'maintenance.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        bot = session.scalar(select(BotInstance))
        assert bot.username == "Fitness_Talks_bot"
        assert bot.is_production is True

    def db_override():
        with Session(engine) as session:
            yield session

    fake = FakeTelegram()
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module, "client", lambda: fake)
    monkeypatch.setattr(main_module.settings, "telegram_webhook_secret", "")
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_mode", True)
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_allowed_user_ids", "42,84")
    monkeypatch.setattr(main_module.settings, "admin_username", "")
    monkeypatch.setattr(main_module.settings, "admin_password", "")
    client = TestClient(app)

    outsider = {"update_id": 200, "message": {"from": {"id": 99, "first_name": "Visitor"}, "chat": {"id": 99}, "text": "/start legacy-code"}}
    assert client.post("/telegram/webhook", json=outsider).json() == {"ok": True, "maintenance": True}
    assert fake.sent[-1][1] == "tpl_maintenance_notice"

    owner = {"update_id": 201, "message": {"from": {"id": 42, "first_name": "Owner"}, "chat": {"id": 42}, "text": "/start"}}
    assert client.post("/telegram/webhook", json=owner).json() == {"ok": True}
    assert fake.sent[-3:] == [
        ("42", "tpl_start_navigation_pin"),
        ("42", "tpl_entry_circle"),
        ("42", "tpl_start_welcome_offer"),
    ]

    plain_start = {"update_id": 203, "message": {"from": {"id": 84, "first_name": "Work owner"}, "chat": {"id": 84}, "text": "старт"}}
    assert client.post("/telegram/webhook", json=plain_start).json() == {"ok": True}
    assert fake.sent[-3:] == [
        ("84", "tpl_start_navigation_pin"),
        ("84", "tpl_entry_circle"),
        ("84", "tpl_start_welcome_offer"),
    ]
    outsider_callback = {"update_id": 202, "callback_query": {"id": "repair-cb", "from": {"id": 99, "first_name": "Visitor"}, "message": {"chat": {"id": 99}}, "data": "start_intensive"}}
    assert client.post("/telegram/webhook", json=outsider_callback).json() == {"ok": True, "maintenance": True}
    assert fake.callbacks[-1] == ("repair-cb", "Бот временно на ремонте")
    assert fake.sent[-1][1] == "tpl_maintenance_notice"

    with Session(engine) as session:
        waiting = session.scalar(select(Contact).where(Contact.telegram_user_id == "99"))
        assert waiting.status == "maintenance_waitlist"
        assert session.scalar(select(func.count(TrackingEvent.id)).where(TrackingEvent.contact_id == waiting.id, TrackingEvent.event_type == "maintenance_contact")) == 2
        assert session.scalar(select(func.count(SequenceRun.id)).where(SequenceRun.contact_id == waiting.id)) == 0
        assert session.scalar(select(Contact).where(Contact.telegram_user_id == "42")).status == "active"

    assert client.post(f"/bot-api/contacts/{waiting.id}/messages", json={"text": "Нельзя отправлять"}).status_code == 409
    app.dependency_overrides.clear()


def test_inbox_timeline_and_safe_broadcast_workflow(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'messaging.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")

    def db_override():
        with Session(engine) as session:
            yield session

    fake = FakeTelegram()
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module, "client", lambda: fake)
    monkeypatch.setattr(main_module.settings, "telegram_webhook_secret", "")
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_mode", True)
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_allowed_user_ids", "42")
    monkeypatch.setattr(main_module.settings, "admin_username", "")
    monkeypatch.setattr(main_module.settings, "admin_password", "")
    client = TestClient(app)

    start = {"update_id": 300, "message": {"message_id": 1, "from": {"id": 42, "first_name": "Owner"}, "chat": {"id": 42}, "text": "/start"}}
    assert client.post("/telegram/webhook", json=start).status_code == 200
    incoming = {"update_id": 301, "message": {"message_id": 2, "from": {"id": 42, "first_name": "Owner"}, "chat": {"id": 42}, "text": "Входящий текст"}}
    assert client.post("/telegram/webhook", json=incoming).status_code == 200
    contact = next(row for row in client.get("/bot-api/contacts").json() if row["telegram_user_id"] == "42")
    timeline = client.get(f"/bot-api/contacts/{contact['id']}/timeline").json()
    assert any(item["direction"] == "incoming" and item["body"] == "Входящий текст" for item in timeline)
    assert client.post(f"/bot-api/contacts/{contact['id']}/messages", json={"text": "Ответ"}).json()["status"] == "sent"
    timeline = client.get(f"/bot-api/contacts/{contact['id']}/timeline").json()
    assert any(item["direction"] == "outgoing" and item["body"] == "Ответ" for item in timeline)

    outsider = {"update_id": 302, "message": {"message_id": 3, "from": {"id": 99, "first_name": "Visitor"}, "chat": {"id": 99}, "text": "Когда откроетесь?"}}
    assert client.post("/telegram/webhook", json=outsider).json() == {"ok": True, "maintenance": True}
    outsider_contact = next(row for row in client.get("/bot-api/contacts").json() if row["telegram_user_id"] == "99")
    outsider_timeline = client.get(f"/bot-api/contacts/{outsider_contact['id']}/timeline").json()
    assert any(item["direction"] == "incoming" and item["body"] == "Когда откроетесь?" for item in outsider_timeline)

    unsafe_media = client.post("/bot-api/broadcasts", json={
        "title": "Нельзя читать файл сервера",
        "text": "Проверка",
        "media_kind": "document",
        "media_path": "../../server-secret",
    })
    assert unsafe_media.status_code == 422

    draft = client.post("/bot-api/broadcasts", json={
        "title": "Проверка рассылки",
        "text": "Тестовый текст",
        "segment": {"status": "active", "telegram_user_ids": ["42"]},
        "buttons": [{"text": "Открыть", "url": "https://example.com"}],
    }).json()
    preview = client.get(f"/bot-api/broadcasts/{draft['id']}/preview").json()
    assert preview["recipient_count"] == 1
    assert preview["maintenance_limited"] is True
    assert client.post(f"/bot-api/broadcasts/{draft['id']}/test", json={"contact_id": contact["id"]}).json()["status"] == "sent"
    assert client.post(f"/bot-api/broadcasts/{draft['id']}/launch", json={"confirmed_recipient_count": 0}).status_code == 409
    launched = client.post(f"/bot-api/broadcasts/{draft['id']}/launch", json={"confirmed_recipient_count": 1}).json()
    assert launched == {"id": draft["id"], "status": "completed", "sent": 1, "failed": 0}
    assert fake.configurations[-1]["buttons"][0]["text"] == "Открыть"
    assert client.post(f"/bot-api/broadcasts/{draft['id']}/retry").status_code == 409
    assert client.get("/bot-api/map?module_code=inbox").json()["issues"] == []
    assert client.get("/bot-api/map?module_code=broadcasts").json()["issues"] == []
    app.dependency_overrides.clear()
