from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import Base, get_db, make_engine
from app.main import app
import app.main as main_module
from app.models import Contact, SequenceRun, StepDelivery, UpdateReceipt
from app.seed import seed_defaults


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.callbacks = []

    def send_content(self, chat_id, content, configuration):
        self.sent.append((chat_id, content.code if hasattr(content, "code") else content.body_source))
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
    assert client.get("/bot").status_code == 200
    assert "Цепочки" in client.get("/bot").text


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
    assert [x[1] for x in fake.sent] == ["tpl_entry_circle", "tpl_entry_welcome"]
    contacts = client.get("/bot-api/contacts").json()
    assert len(contacts) == 1
    assert contacts[0]["run_status"] == "waiting"
    callback = {"update_id": 101, "callback_query": {"id": "cb-1", "from": {"id": 42, "first_name": "Sergey", "username": "tester"}, "message": {"chat": {"id": 42}}, "data": "start_intensive"}}
    assert client.post("/telegram/webhook", json=callback).json() == {"ok": True}
    repeat = {"update_id": 102, "message": {"from": {"id": 42, "first_name": "Sergey", "username": "tester"}, "chat": {"id": 42}, "text": "/start"}}
    assert client.post("/telegram/webhook", json=repeat).json() == {"ok": True}
    assert len(fake.sent) == 3
    assert "Следующее сообщение" in fake.sent[-1][1]
    assert "tpl_day1" not in [item[1] for item in fake.sent]
    overview = client.get("/bot-api/map").json()
    assert overview["level"] == "overview"
    assert any(node["id"] == "route:main_start" for node in overview["nodes"])
    detail = client.get("/bot-api/map?sequence_code=prepurchase_masterclass").json()
    assert detail["level"] == "sequence"
    assert any(edge["branch"] == "true" for edge in detail["edges"])
    crm_user_id = "11111111-1111-1111-1111-111111111111"
    with Session(engine) as session:
        contact = session.scalar(select(Contact))
        contact.user_id = crm_user_id
        session.commit()
        assert session.scalar(select(func.count(Contact.id))) == 1
        assert session.scalar(select(func.count(SequenceRun.id))) == 1
        assert session.scalar(select(func.count(StepDelivery.id))) == 2
        assert session.scalar(select(func.count(UpdateReceipt.update_id))) == 3
    state = client.get(f"/bot-api/users/{crm_user_id}").json()
    assert state["run_status"] == "waiting"
    assert state["sent"] == 2
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
