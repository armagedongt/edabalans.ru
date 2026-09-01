import base64
import hashlib
import os
import time
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.intensive_login_routes import router
from app.models import TelegramLoginAttempt, User


def setup(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(database_url="sqlite://", app_auth_secret="secret", telegram_test_bot_username="Fitness_Talks_bot")
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.dependency_overrides[get_db] = lambda: (yield from _db(factory))
    test_app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(test_app, base_url="https://app.edabalans.ru"), factory


def _db(factory):
    with factory() as db:
        yield db


def test_browser_starts_pending_then_receives_linked_identity(tmp_path):
    client, factory = setup(tmp_path)
    assert client.get("/telegram-login").status_code == 200
    started = client.post("/api/intensive/telegram-login/start")
    assert started.status_code == 200
    payload = started.json()["deep_link"].split("?start=",1)[1]
    assert payload.startswith("I") and len(payload) <= 64
    assert client.get("/api/intensive/telegram-login/status").json()["reason"] == "pending"
    cookie = client.cookies.get("edabalans_tg_attempt")
    raw = cookie.rsplit(".",1)[0]
    nonce = base64.urlsafe_b64decode(raw + "=" * (-len(raw)%4))
    with factory() as db:
        user = User(display_name="Сергей", status="active", data_origin="native")
        db.add(user); db.flush()
        db.add(TelegramLoginAttempt(nonce_hash=hashlib.sha256(nonce).hexdigest(),user_id=user.id,telegram_user_id="42",username="sergey",first_name="Сергей",verification_code_hash=hashlib.sha256(b"123456").hexdigest(),expires_at=datetime.now(timezone.utc)+timedelta(minutes=15),consumed_at=datetime.now(timezone.utc)))
        db.commit()
    assert client.get("/api/intensive/telegram-login/status").json()["reason"] == "code_required"
    assert client.post("/api/intensive/telegram-login/confirm", json={"code":"000000"}).status_code == 422
    linked = client.post("/api/intensive/telegram-login/confirm", json={"code":"123456"})
    assert linked.json() == {"linked":True,"user":{"first_name":"Сергей","username":"sergey"}}
    assert client.cookies.get("edabalans_tg_session")
    assert client.get("/api/intensive/telegram-login/status").json()["linked"] is True
