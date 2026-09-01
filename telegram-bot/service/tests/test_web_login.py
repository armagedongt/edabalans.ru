import base64
import hashlib
import hmac
import re
import struct
import time

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.models import BotInstance, Contact, CrmMessengerAccount, CrmUser, TelegramLoginAttempt
from app.web_login import consume_web_login
from app.seed import seed_defaults
import app.main as main_module


def payload(secret: str, *, age: int = 0) -> tuple[str, bytes]:
    nonce = b"0123456789abcdef"
    head = struct.pack(">I16s", int(time.time()) - age, nonce)
    mac = hmac.new(secret.encode(), b"I" + head, hashlib.sha256).digest()[:12]
    return "I" + base64.urlsafe_b64encode(head + mac).decode().rstrip("="), nonce


def setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'web-login.sqlite'}")
    Base.metadata.create_all(engine)
    return engine


def test_valid_payload_records_real_telegram_identity(tmp_path):
    engine = setup(tmp_path)
    with Session(engine) as session:
        user = CrmUser(display_name="Сергей", status="active", data_origin="native")
        bot = BotInstance(code="test", username="bot", display_name="bot", token_env_name="TOKEN", is_active=True)
        session.add_all([user, bot]); session.flush()
        contact = Contact(bot_instance_id=bot.id, user_id=user.id, telegram_user_id="42", chat_id="42", status="active")
        account = CrmMessengerAccount(user_id=user.id, platform="telegram", platform_user_id="42", source="telegram_bot")
        session.add_all([contact, account]); session.flush()
        token, nonce = payload("secret")
        handled, reply, variables = consume_web_login(session, contact, {"id":42,"username":"sergey","first_name":"Сергей"}, token, "secret")
        session.commit()
        row = session.scalar(select(TelegramLoginAttempt))
        assert handled and reply == "web_login_code"
        assert variables["login_code"].isdigit() and len(variables["login_code"]) == 6
        assert row.nonce_hash == hashlib.sha256(nonce).hexdigest()
        assert row.user_id == user.id and row.telegram_user_id == "42"


def test_expired_or_tampered_payload_does_not_log_in(tmp_path):
    engine = setup(tmp_path)
    with Session(engine) as session:
        token, _ = payload("secret", age=901)
        handled, reply, _ = consume_web_login(session, Contact(telegram_user_id="42"), {"id":42}, token, "secret")
        assert handled and reply == "web_login_invalid"
        assert session.scalar(select(TelegramLoginAttempt)) is None
        handled, _, _ = consume_web_login(session, Contact(telegram_user_id="42"), {"id":42}, token[:-1]+"A", "secret")
        assert handled and session.scalar(select(TelegramLoginAttempt)) is None


def test_process_update_delivers_code_only_to_maintenance_allowlist(tmp_path, monkeypatch):
    engine = setup(tmp_path)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        session.commit()
    sent = []
    class FakeTelegram:
        def send_content(self, chat_id, content, variables):
            sent.append((chat_id, content.body_source, variables))
            return "1"
    monkeypatch.setattr(main_module, "client", lambda: FakeTelegram())
    monkeypatch.setattr(main_module.settings, "app_auth_secret", "secret")
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_mode", True)
    monkeypatch.setattr(main_module.settings, "telegram_maintenance_allowed_user_ids", "42")
    owner_token, _ = payload("secret")
    with Session(engine) as session:
        result = main_module.process_update({"update_id":1,"message":{"from":{"id":42,"first_name":"Сергей"},"chat":{"id":42},"text":f"/start {owner_token}"}}, session)
        assert result == {"ok":True,"web_login":True}
        assert "{{login_code}}" not in sent[-1][1]
        delivered_code = re.search(r"(?<!\d)(\d{6})(?!\d)", sent[-1][1]).group(1)
        attempt = session.scalar(select(TelegramLoginAttempt))
        assert hashlib.sha256(delivered_code.encode()).hexdigest() == attempt.verification_code_hash
        assert sent[-1][2] == {}
        before = session.scalar(select(func.count(TelegramLoginAttempt.id)))
    outsider_token, _ = payload("secret")
    with Session(engine) as session:
        result = main_module.process_update({"update_id":2,"message":{"from":{"id":99,"first_name":"Другой"},"chat":{"id":99},"text":f"/start {outsider_token}"}}, session)
        assert result == {"ok":True,"maintenance":True,"web_login":True}
        assert session.scalar(select(func.count(TelegramLoginAttempt.id))) == before
