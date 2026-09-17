from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import Base, get_db, make_engine
from app.main import app
import app.main as main_module
from app.models import BotInstance, Broadcast, Contact, ContentItem, CrmMessengerAccount, CrmUser, MessengerLinkToken, SequenceRun, StepDelivery, TrackingEvent, UpdateReceipt
from app.seed import seed_defaults
from app.telegram import TelegramError


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.callbacks = []
        self.configurations = []
        self.menu_apps = []
        self.reset_menu_buttons = []
        self.edited = []

    def send_content(self, chat_id, content, configuration):
        self.sent.append((chat_id, content.code if hasattr(content, "code") else content.body_source))
        self.configurations.append(configuration)
        return str(len(self.sent))

    def answer_callback(self, callback_query_id, text=""):
        self.callbacks.append((callback_query_id, text))

    def set_chat_menu_web_app(self, chat_id, text, url):
        self.menu_apps.append((chat_id, text, url))

    def reset_chat_menu_button(self, chat_id):
        self.reset_menu_buttons.append(chat_id)

    def edit_content(self, chat_id, message_id, content, configuration):
        self.edited.append((chat_id, message_id, content.body_source, configuration))


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


def test_internal_owner_payment_alert_uses_signed_payload_and_active_owner_contact(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'owner-alert.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        bot = session.scalar(select(BotInstance).where(BotInstance.is_active.is_(True)))
        assert bot is not None
        session.add(
            Contact(
                bot_instance_id=bot.id,
                telegram_user_id="77",
                chat_id="77",
                username="svorontsovski",
                status="active",
            )
        )
        session.commit()

    def db_override():
        with Session(engine) as session:
            yield session

    class PaymentAlertTelegram:
        def __init__(self):
            self.calls = []

        def call(self, method, payload):
            self.calls.append((method, payload))
            return {"message_id": 444}

    fake = PaymentAlertTelegram()
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module, "client", lambda: fake)
    monkeypatch.setattr(main_module.settings, "app_auth_secret", "owner-alert-tests")
    monkeypatch.setattr(main_module.settings, "payment_owner_telegram_user_id", "77")
    payload = {"notification_id": "a12", "message_text": "Оплата прошла\nСумма: 9 900 ₽"}
    signature = main_module._owner_payment_alert_signature(
        payload["notification_id"], payload["message_text"]
    )
    client = TestClient(app)

    accepted = client.post(
        "/internal/owner-payment-alert",
        json=payload,
        headers={"X-Edabalans-Payment-Signature": signature},
    )
    repeated = client.post(
        "/internal/owner-payment-alert",
        json=payload,
        headers={"X-Edabalans-Payment-Signature": signature},
    )
    rejected = client.post("/internal/owner-payment-alert", json=payload)

    assert accepted.status_code == 200
    assert accepted.json() == {"ok": True, "message_id": "444"}
    assert repeated.status_code == 200
    assert repeated.json() == {"ok": True, "message_id": "444"}
    assert fake.calls == [("sendMessage", {"chat_id": "77", "text": payload["message_text"], "disable_web_page_preview": True})]
    assert rejected.status_code == 403
    app.dependency_overrides.clear()


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
    assert [x[1] for x in fake.sent] == ["tpl_entry_circle", "tpl_intensive_entry_default"]
    assert fake.menu_apps == []
    assert fake.reset_menu_buttons == ["42"]
    contacts = client.get("/bot-api/contacts").json()
    assert len(contacts) == 1
    assert contacts[0]["run_status"] == "active"
    callback = {"update_id": 101, "callback_query": {"id": "cb-1", "from": {"id": 42, "first_name": "Sergey", "username": "tester"}, "message": {"chat": {"id": 42}}, "data": "start_intensive"}}
    assert client.post("/telegram/webhook", json=callback).json() == {"ok": True}
    repeat = {"update_id": 102, "message": {"from": {"id": 42, "first_name": "Sergey", "username": "tester"}, "chat": {"id": 42}, "text": "/start"}}
    assert client.post("/telegram/webhook", json=repeat).json() == {"ok": True}
    assert len(fake.sent) == 3
    assert fake.sent[-1][1] == "tpl_intensive_entry_continue"
    assert fake.reset_menu_buttons == ["42", "42"]
    assert "tpl_day1" not in [item[1] for item in fake.sent]
    overview = client.get("/bot-api/map").json()
    assert overview["level"] == "overview"
    assert any(node["id"] == "module:start_attribution" for node in overview["nodes"])
    sequences = client.get("/bot-api/sequences").json()
    assert [item["code"] for item in sequences[:3]] == ["start_attribution", "welcome_intensive", "prepurchase_nurture"]
    assert "prepurchase_masterclass" not in [item["code"] for item in sequences]
    module = client.get("/bot-api/map?module_code=start_attribution").json()
    assert module["level"] == "module"
    assert any(node["id"] == "exit_welcome" and node["kind"] == "module_exit" for node in module["nodes"])
    assert any(node["id"] == "send_legacy" and node["kind"] == "message" for node in module["nodes"])
    assert any(edge["source"] == "welcome_run_active" and edge["target"] == "welcome_ever_started" and edge["branch"] == "false" for edge in module["edges"])
    assert any(edge["source"] == "welcome_ever_started" and edge["target"] == "exit_welcome" and edge["branch"] == "false" for edge in module["edges"])
    assert any(edge["source"] == "welcome_ever_started" and edge["target"] == "send_legacy" and edge["branch"] == "true" for edge in module["edges"])
    detail = client.get("/bot-api/map?sequence_code=welcome_intensive").json()
    assert detail["level"] == "sequence"
    assert len([node for node in detail["nodes"] if node["kind"] in {"message", "video_note"}]) == 14
    day2_node = next(node for node in detail["nodes"] if node["id"] == "welcome_day2")
    assert day2_node["content"]["code"] == "tpl_intensive_day2"
    old_url = day2_node["configuration"]["buttons"][0]["url"]
    edited_button = client.patch(f"/bot-api/steps/{day2_node['step_id']}/presentation", json={"button_text": "Открыть часть #2"})
    assert edited_button.status_code == 200
    assert edited_button.json()["configuration"]["buttons"][0]["text"] == "Открыть часть #2"
    assert edited_button.json()["configuration"]["buttons"][0]["url"] == old_url
    assert any(edge["branch"] == "true" for edge in detail["edges"])
    postpurchase_map = client.get("/bot-api/map?module_code=postpurchase_masterclass").json()
    assert postpurchase_map["level"] == "module"
    assert any(node["id"] == "pp_closing_review_copy" for node in postpurchase_map["nodes"])
    review_condition = next(node for node in postpurchase_map["nodes"] if node["id"] == "condition:pp_closing_review_copy")
    assert "telegram_linked=true" in review_condition["details"]["Точный факт"]
    assert not any(node["id"].startswith("pp_review_week_day") for node in postpurchase_map["nodes"])
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
        assert session.scalar(select(func.count(StepDelivery.id))) == 0
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


def test_telegram_stop_and_block_events_stop_only_that_contacts_schedule(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'stop-events.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        bot = session.scalar(select(BotInstance))
        user = CrmUser(display_name="Получатель")
        session.add(user); session.flush()
        contact = Contact(
            bot_instance_id=bot.id,
            user_id=user.id,
            telegram_user_id="42",
            chat_id="42",
        )
        session.add(contact); session.flush()
        from app.engine import start_run
        start_run(session, contact.id, "welcome_intensive")
        session.commit()

    def db_override():
        with Session(engine) as session:
            yield session

    fake = FakeTelegram()
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module, "client", lambda: fake)
    monkeypatch.setattr(main_module.settings, "telegram_webhook_secret", "")
    client = TestClient(app)

    response = client.post("/telegram/webhook", json={
        "update_id": 900,
        "message": {
            "from": {"id": 42, "first_name": "Получатель"},
            "chat": {"id": 42, "type": "private"},
            "text": "/stop",
        },
    })
    assert response.json() == {"ok": True, "stopped": True, "stopped_runs": 1}
    assert fake.sent[-1][1] == "system_stop_confirmation"

    response = client.post("/telegram/webhook", json={
        "update_id": 901,
        "my_chat_member": {
            "chat": {"id": 42, "type": "private"},
            "new_chat_member": {"status": "kicked"},
        },
    })
    assert response.json() == {"ok": True}
    with Session(engine) as session:
        contact = session.scalar(select(Contact).where(Contact.telegram_user_id == "42"))
        events = list(session.scalars(select(TrackingEvent).where(TrackingEvent.event_type == "bot_stopped")))
        assert contact.status == "stopped"
        assert len(events) == 2
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
    assert fake.sent[-2:] == [
        ("42", "tpl_entry_circle"),
        ("42", "tpl_intensive_entry_default"),
    ]

    plain_start = {"update_id": 203, "message": {"from": {"id": 84, "first_name": "Work owner"}, "chat": {"id": 84}, "text": "старт"}}
    assert client.post("/telegram/webhook", json=plain_start).json() == {"ok": True}
    assert fake.sent[-2:] == [
        ("84", "tpl_entry_circle"),
        ("84", "tpl_intensive_entry_default"),
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


def test_app_deep_link_and_refresh_work_during_maintenance(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'apps-link.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(text("""
            CREATE TABLE resources (
                id TEXT PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL
            )
        """))
        session.execute(text("""
            CREATE TABLE user_accesses (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                expires_at TIMESTAMP NULL,
                revoked_at TIMESTAMP NULL
            )
        """))
        session.execute(text("""
            CREATE TABLE masterclass_events (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                event_type TEXT NOT NULL
            )
        """))
        seed_defaults(session, "Fitness_Talks_bot")
        user = CrmUser(display_name="DQS user", status="active", data_origin="native")
        session.add(user)
        session.flush()
        resource_id = str(uuid4())
        session.execute(
            text("INSERT INTO resources (id, code, status) VALUES (:id, 'dqs', 'active')"),
            {"id": resource_id},
        )
        session.add(
            CrmMessengerAccount(
                user_id=user.id,
                platform="telegram",
                platform_user_id="99",
                first_seen_at=None,
                last_seen_at=None,
                linked_at=None,
                source="test",
            )
        )
        session.execute(text("""
            INSERT INTO user_accesses (id, user_id, resource_id, expires_at, revoked_at)
            VALUES (:id, :user_id, :resource_id, NULL, NULL)
        """), {"id": str(uuid4()), "user_id": user.id, "resource_id": resource_id})
        session.execute(
            text("""
                INSERT INTO masterclass_events (id, user_id, event_type)
                VALUES (:id, :user_id, 'app_revealed_dqs')
            """),
            {"id": str(uuid4()), "user_id": user.id},
        )
        session.commit()

    def db_override():
        with Session(engine) as session:
            yield session

    fake = FakeTelegram()
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module, "client", lambda: fake)
    monkeypatch.setattr(main_module.settings, "telegram_webhook_secret", "")
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_mode", True)
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_allowed_user_ids", "42")
    client = TestClient(app)

    opened = {"update_id": 300, "message": {"from": {"id": 99, "first_name": "Visitor"}, "chat": {"id": 99}, "text": "/start dqs"}}
    assert client.post("/telegram/webhook", json=opened).json() == {"ok": True, "apps_menu": True}
    assert {
        "text": "Оценка качества питания",
        "web_app": {"url": "https://edabalans.ru/dqs"},
        "max_app_payload": "dqs",
    } in fake.configurations[-1]["buttons"]

    refreshed = {"update_id": 301, "callback_query": {"id": "apps-cb", "from": {"id": 99, "first_name": "Visitor"}, "message": {"chat": {"id": 99}, "message_id": 7}, "data": "apps:refresh"}}
    assert client.post("/telegram/webhook", json=refreshed).json() == {"ok": True, "apps_menu": True}
    assert fake.edited[-1][0:2] == ("99", "7")
    assert fake.callbacks[-1] == ("apps-cb", "Список обновлён")
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


def test_broadcast_personal_links_are_per_recipient_and_survive_retry(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'broadcast-personal.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "FixtureBot")
        bot = session.scalar(select(BotInstance).where(BotInstance.code == "test"))
        contact_ids = {}
        for number in (42, 43, 44):
            user_id = str(uuid4()) if number != 44 else None
            if user_id:
                session.add(CrmUser(id=user_id))
                session.flush()
            contact = Contact(bot_instance_id=bot.id, user_id=user_id, telegram_user_id=str(number), chat_id=str(number))
            session.add(contact)
            session.flush()
            contact_ids[number] = contact.id
        session.commit()

    def db_override():
        with Session(engine) as session:
            yield session

    class PersonalSender(FakeTelegram):
        def __init__(self):
            super().__init__()
            self.deliveries = []
            self.fail_once = True

        def send_content(self, chat_id, content, configuration):
            self.deliveries.append((chat_id, content.body_source, configuration))
            if chat_id == "43" and self.fail_once:
                self.fail_once = False
                raise TelegramError("Fixture temporary failure")
            if content.media_kind == "photo":
                content.telegram_file_id = "fixture-photo-file"
            return super().send_content(chat_id, content, configuration)

    fake = PersonalSender()
    monkeypatch.setattr(main_module, "client", lambda: fake)
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_mode", True)
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_allowed_user_ids", "42,43,44")
    monkeypatch.setattr(main_module.settings, "admin_username", "")
    monkeypatch.setattr(main_module.settings, "admin_password", "")
    app.dependency_overrides[get_db] = db_override
    try:
        client = TestClient(app)
        template = '<a href="{{ personal_masterclass_url }}">Мастер-класс</a>'
        for invalid_url in ("{{unknown_url}}", "{{personal_intensive_current_day_url}}", "javascript:alert(1)"):
            rejected = client.post("/bot-api/broadcasts", json={"title": "Fixture", "text": template, "buttons": [{"text": "Открыть", "url": invalid_url}]})
            assert rejected.status_code == 422
        draft_response = client.post("/bot-api/broadcasts", json={
            "title": "Personal fixture", "text": template,
            "segment": {"status": "active", "telegram_user_ids": ["42", "43"]},
            "buttons": [{"text": "Открыть", "url": "{{personal_masterclass_url}}"}],
        })
        assert draft_response.status_code == 200
        draft = draft_response.json()
        assert client.post(f"/bot-api/broadcasts/{draft['id']}/test", json={"contact_id": contact_ids[42]}).status_code == 200
        launched = client.post(f"/bot-api/broadcasts/{draft['id']}/launch", json={"confirmed_recipient_count": 2}).json()
        assert (launched["sent"], launched["failed"]) == (1, 1)
        retried = client.post(f"/bot-api/broadcasts/{draft['id']}/retry").json()
        assert (retried["sent"], retried["failed"]) == (1, 0)
        deliveries = {number: [item for item in fake.deliveries if item[0] == str(number)] for number in (42, 43)}
        assert len(deliveries[42]) == 2  # owner-test and initial send, not retry
        assert len(deliveries[43]) == 2  # failed initial send and retry
        urls = {}
        for number, attempts in deliveries.items():
            urls[number] = attempts[0][2]["buttons"][0]["url"]
            assert urls[number].startswith("https://go.похудение-это-есть.рф/m/E")
            for _, body, configuration in attempts:
                assert "{{" not in body and "{{" not in str(configuration)
                assert f'href="{urls[number]}"' in body
                assert configuration["buttons"][0]["url"] == urls[number]
        assert urls[42] != urls[43]

        body_only_draft = client.post("/bot-api/broadcasts", json={
            "title": "Whitespace body fixture", "text": template,
            "media_kind": "photo", "media_path": "https://example.com/fixture.jpg",
            "segment": {"telegram_user_ids": ["42"]},
        }).json()
        body_only_result = client.post(f"/bot-api/broadcasts/{body_only_draft['id']}/launch", json={"confirmed_recipient_count": 1}).json()
        assert (body_only_result["sent"], body_only_result["failed"]) == (1, 0)
        assert f'href="{urls[42]}"' in fake.deliveries[-1][1]
        assert fake.deliveries[-1][2]["buttons"] == []

        before = len(fake.deliveries)
        anonymous_draft = client.post("/bot-api/broadcasts", json={"title": "No CRM fixture", "text": template, "segment": {"telegram_user_ids": ["44"]}}).json()
        anonymous_result = client.post(f"/bot-api/broadcasts/{anonymous_draft['id']}/launch", json={"confirmed_recipient_count": 1}).json()
        assert (anonymous_result["sent"], anonymous_result["failed"]) == (0, 1)
        assert len(fake.deliveries) == before
        unresolved_draft = client.post("/bot-api/broadcasts", json={
            "title": "Unresolved fixture", "text": '<a href="{{personal_intensive_current_day_url}}">Текущий день</a>',
            "segment": {"telegram_user_ids": ["42"]},
        }).json()
        unresolved_result = client.post(f"/bot-api/broadcasts/{unresolved_draft['id']}/launch", json={"confirmed_recipient_count": 1}).json()
        assert (unresolved_result["sent"], unresolved_result["failed"]) == (0, 1)
        assert len(fake.deliveries) == before
        with Session(engine) as session:
            row = session.get(Broadcast, draft["id"])
            assert session.get(ContentItem, row.content_item_id).body_source == template
            assert row.segment["_buttons"][0]["url"] == "{{personal_masterclass_url}}"
            media_row = session.get(Broadcast, body_only_draft["id"])
            assert session.get(ContentItem, media_row.content_item_id).telegram_file_id == "fixture-photo-file"
            assert session.scalar(select(func.count()).select_from(MessengerLinkToken)) == 2
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_start_continues_when_telegram_rate_limits_optional_menu_reset(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'menu-rate-limit.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        session.commit()

    class RateLimitedMenuTelegram(FakeTelegram):
        def reset_chat_menu_button(self, chat_id):
            raise TelegramError("Telegram API HTTP 429")

    def db_override():
        with Session(engine) as session:
            yield session

    fake = RateLimitedMenuTelegram()
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main_module, "client", lambda: fake)
    monkeypatch.setattr(main_module.settings, "telegram_webhook_secret", "")
    response = TestClient(app).post(
        "/telegram/webhook",
        json={"update_id": 103, "message": {"from": {"id": 43, "first_name": "Sergey"}, "chat": {"id": 43}, "text": "/start"}},
    )

    assert response.json() == {"ok": True}
    assert [entry[1] for entry in fake.sent] == ["tpl_entry_circle", "tpl_intensive_entry_default"]
    with Session(engine) as session:
        assert session.scalar(select(func.count(UpdateReceipt.update_id))) == 1
    app.dependency_overrides.clear()
