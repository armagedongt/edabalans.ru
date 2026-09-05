import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.masterclass_link import consume_masterclass_link
from app.models import (
    AccountOnboarding,
    BotInstance,
    Contact,
    CrmMessengerAccount,
    CrmUser,
    AccountCredential,
    MasterclassNotification,
    MessengerLinkToken,
    Sequence,
    SequenceRun,
    SequenceVersion,
)


def test_one_time_link_reassigns_disposable_bot_identity_and_queues_two_messages(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'link.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for ddl in (
            "CREATE TABLE user_emails (id TEXT, user_id TEXT, email_original TEXT, is_primary BOOLEAN, created_at DATETIME)",
            "CREATE TABLE user_accesses (id TEXT, user_id TEXT)",
            "CREATE TABLE payments (id TEXT, user_id TEXT)",
        ):
            session.execute(text(ddl))
        target = CrmUser(display_name="Покупатель", status="active", data_origin="native")
        placeholder = CrmUser(display_name="Telegram", status="active", data_origin="native")
        bot = BotInstance(code="test", username="test", display_name="test", token_env_name="TOKEN", is_active=True)
        session.add_all([target, placeholder, bot]); session.flush()
        contact = Contact(bot_instance_id=bot.id, user_id=placeholder.id, telegram_user_id="42", chat_id="42", status="active")
        account = CrmMessengerAccount(user_id=placeholder.id, platform="telegram", platform_user_id="42", source="telegram_bot")
        session.add_all([contact, account]); session.flush()
        welcome = Sequence(code="welcome_intensive", name="Welcome", status="published")
        session.add(welcome); session.flush()
        version = SequenceVersion(sequence_id=welcome.id, version_no=1, status="published")
        session.add(version); session.flush()
        presale_run = SequenceRun(contact_id=contact.id, sequence_version_id=version.id, status="waiting")
        payload = "Mtest-token"
        token = MessengerLinkToken(
            user_id=target.id,
            platform="telegram",
            purpose="link_account",
            token_hash=hashlib.sha256(payload.encode("ascii")).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add_all([presale_run, token]); session.commit()

        handled, reply = consume_masterclass_link(
            session,
            contact,
            {"id": 42, "username": "owner", "first_name": "Сергей"},
            payload,
        )
        session.commit()

        assert handled is True
        assert "привязан" in reply
        assert contact.user_id == target.id
        assert account.user_id == target.id
        assert token.consumed_at is not None
        assert presale_run.status == "completed"
        assert presale_run.context["stopped_reason"] == "messenger_link_confirmed"
        queued = list(session.scalars(select(MasterclassNotification).where(MasterclassNotification.user_id == target.id)))
        assert [row.notification_kind for row in queued] == ["messenger_identity", "messenger_questionnaire"]


def test_used_link_is_not_consumed_twice(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'used-link.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        target = CrmUser(display_name="Покупатель", status="active", data_origin="native")
        bot = BotInstance(code="test", username="test", display_name="test", token_env_name="TOKEN", is_active=True)
        session.add_all([target, bot]); session.flush()
        contact = Contact(bot_instance_id=bot.id, user_id=target.id, telegram_user_id="42", chat_id="42", status="active")
        account = CrmMessengerAccount(user_id=target.id, platform="telegram", platform_user_id="42", source="masterclass_link")
        payload = "Mused-token"
        token = MessengerLinkToken(
            user_id=target.id,
            platform="telegram",
            purpose="link_account",
            token_hash=hashlib.sha256(payload.encode("ascii")).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            consumed_at=datetime.now(UTC),
        )
        session.add_all([contact, account, token]); session.commit()

        handled, reply = consume_masterclass_link(session, contact, {"id": 42}, payload)

        assert handled is True
        assert "уже использована" in reply
        assert session.scalar(select(MasterclassNotification.id)) is None


def test_account_claim_creates_password_once_and_queues_questionnaire(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'account-claim.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for ddl in (
            "CREATE TABLE user_emails (id TEXT, user_id TEXT, email_original TEXT, email_normalized TEXT, is_primary BOOLEAN, created_at DATETIME)",
            "CREATE TABLE user_accesses (id TEXT, user_id TEXT)",
            "CREATE TABLE payments (id TEXT, user_id TEXT)",
        ):
            session.execute(text(ddl))
        target = CrmUser(display_name="Покупатель", status="active", data_origin="native")
        placeholder = CrmUser(display_name="Telegram", status="active", data_origin="native")
        bot = BotInstance(code="test", username="test", display_name="test", token_env_name="TOKEN", is_active=True)
        session.add_all([target, placeholder, bot])
        session.flush()
        session.execute(
            text("INSERT INTO user_emails (id,user_id,email_original,email_normalized,is_primary,created_at) VALUES ('e1',:user_id,'member@example.test','member@example.test',1,CURRENT_TIMESTAMP)"),
            {"user_id": target.id},
        )
        contact = Contact(bot_instance_id=bot.id, user_id=placeholder.id, telegram_user_id="42", chat_id="42", status="active")
        account = CrmMessengerAccount(user_id=placeholder.id, platform="telegram", platform_user_id="42", source="telegram_bot")
        payload = "Maccount-token"
        onboarding = AccountOnboarding(
            user_id=target.id,
            payment_id="00000000-0000-0000-0000-000000000001",
            claim_bundle_encrypted="test-bundle",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add(onboarding)
        session.flush()
        token = MessengerLinkToken(
            user_id=target.id,
            account_onboarding_id=onboarding.id,
            platform="telegram",
            purpose="account_credentials",
            token_hash=hashlib.sha256(payload.encode("ascii")).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add_all([contact, account, token])
        session.commit()

        handled, reply = consume_masterclass_link(
            session,
            contact,
            {"id": 42, "username": "owner", "first_name": "Сергей"},
            payload,
            "test-secret",
            "https://go.example.test/lk",
        )
        session.commit()

        assert handled is True
        assert "Логин" in reply and "Пароль" in reply
        assert "https://go.example.test/lk" in reply
        assert session.get(AccountCredential, target.id) is not None
        assert onboarding.status == "claimed"
        assert onboarding.claimed_platform == "telegram"
        assert onboarding.claimed_at is not None
        queued = list(session.scalars(select(MasterclassNotification).where(MasterclassNotification.user_id == target.id)))
        assert [row.notification_kind for row in queued] == ["messenger_questionnaire"]
