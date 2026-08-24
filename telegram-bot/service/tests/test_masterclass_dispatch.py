from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.masterclass_dispatch import client_values, dispatch_due_masterclass_notifications
from app.models import BotInstance, Contact, ContentItem, MasterclassNotification


class FakeSender:
    def __init__(self):
        self.sent = []

    def send_content(self, chat_id, content, configuration):
        self.sent.append((chat_id, content.code, content.body_source))
        return str(len(self.sent))


def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'dispatch.sqlite'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.execute(text(
        "CREATE TABLE IF NOT EXISTS masterclass_events ("
        "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, event_type TEXT NOT NULL, "
        "occurred_at DATETIME NOT NULL)"
    ))
    session.commit()
    return session


def add_contact_and_content(session):
    bot = BotInstance(code="test", username="test", display_name="test", token_env_name="TOKEN", is_active=True)
    session.add(bot); session.flush()
    contact = Contact(bot_instance_id=bot.id, user_id="11111111-1111-1111-1111-111111111111", telegram_user_id="42", chat_id="42", status="active")
    session.add(contact)
    for code in (
        "tpl_postpurchase_recipes_missing",
        "tpl_postpurchase_recipes_owned",
        "tpl_postpurchase_review_consultation",
        "tpl_postpurchase_tempo_late",
        "tpl_postpurchase_final_offer",
    ):
        session.add(ContentItem(code=code, title=code, body_source="Откройте {{offers_url}}", status="published"))
    session.flush()
    return contact


def test_client_summary_uses_masterclass_payment_and_human_question_titles(tmp_path):
    with session_factory(tmp_path) as session:
        contact = add_contact_and_content(session)
        for ddl in (
            "CREATE TABLE user_emails (user_id TEXT, email_original TEXT, is_primary BOOLEAN, created_at DATETIME)",
            "CREATE TABLE resources (id TEXT PRIMARY KEY, code TEXT)",
            "CREATE TABLE user_accesses (user_id TEXT, resource_id TEXT, source_payment_id TEXT, revoked_at DATETIME, expires_at DATETIME)",
            "CREATE TABLE payments (id TEXT PRIMARY KEY, product_name_raw TEXT, paid_at DATETIME, source_event_at DATETIME, created_at DATETIME)",
            "CREATE TABLE questionnaire_runs (id TEXT PRIMARY KEY, user_id TEXT, kind TEXT)",
            "CREATE TABLE questionnaire_answers (run_id TEXT, question_code TEXT, answer_text TEXT, updated_at DATETIME)",
        ):
            session.execute(text(ddl))
        user_id = contact.user_id
        session.execute(text(
            "INSERT INTO user_emails VALUES (:user_id, 'buyer@example.com', 1, CURRENT_TIMESTAMP)"
        ), {"user_id": user_id})
        session.execute(text("INSERT INTO resources VALUES ('mc', 'ACCESS_MASTERCLASS')"))
        session.execute(text(
            "INSERT INTO payments VALUES ('mc-payment', 'Мастер-класс · самостоятельный', CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP)"
        ))
        session.execute(text(
            "INSERT INTO payments VALUES ('later-payment', 'Рецепты', CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP)"
        ))
        session.execute(text(
            "INSERT INTO user_accesses VALUES (:user_id, 'mc', 'mc-payment', NULL, NULL)"
        ), {"user_id": user_id})
        session.execute(text(
            "INSERT INTO questionnaire_runs VALUES ('run', :user_id, 'onboarding')"
        ), {"user_id": user_id})
        session.execute(text(
            "INSERT INTO questionnaire_answers VALUES ('run', 'main_request', 'Хочу устойчиво похудеть', CURRENT_TIMESTAMP)"
        ))
        session.commit()

        values = client_values(
            session,
            contact,
            "https://example.test/offers",
            "https://example.test/course",
            "https://example.test/account",
            "{{email}} {{masterclass_tariff}} {{questionnaire_formatted}}",
        )

        assert values["email"] == "buyer@example.com"
        assert values["masterclass_tariff"] == "Мастер-класс · самостоятельный"
        assert "Главный запрос" in values["questionnaire_formatted"]
        assert "main_request" not in values["questionnaire_formatted"]


def test_dispatch_chooses_message_from_current_access_and_is_idempotent(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        row = MasterclassNotification(
            id="22222222-2222-2222-2222-222222222222",
            user_id="11111111-1111-1111-1111-111111111111",
            notification_kind="recipes_followup",
            deduplication_key="recipes:1",
            due_at=datetime.now(UTC) - timedelta(seconds=1),
            status="pending",
            payload={},
        )
        session.add(row); session.commit()
        sender = FakeSender()
        result = dispatch_due_masterclass_notifications(session, sender, "https://example.test/offers", lambda *_: {"ACCESS_MASTERCLASS"})
        assert result["sent"] == 1
        assert sender.sent == [("42", "tpl_postpurchase_recipes_missing", "Откройте https://example.test/offers")]
        assert dispatch_due_masterclass_notifications(session, sender, "https://example.test/offers", lambda *_: set())["sent"] == 0


def test_dispatch_skips_recipe_upsell_when_everything_is_owned(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        session.add(MasterclassNotification(
            id="33333333-3333-3333-3333-333333333333",
            user_id="11111111-1111-1111-1111-111111111111",
            notification_kind="recipes_followup",
            deduplication_key="recipes:all",
            due_at=datetime.now(UTC) - timedelta(seconds=1),
            status="pending",
            payload={},
        ))
        session.commit()
        sender = FakeSender()
        result = dispatch_due_masterclass_notifications(session, sender, "", lambda *_: {"ACCESS_MASTERCLASS", "ACCESS_RECIPES", "ACCESS_CALORIES", "ACCESS_STRENGTH", "ACCESS_CONSULTATION_RECORDINGS"})
        assert result["skipped"] == 1
        assert sender.sent == []


def test_dispatch_leaves_outsider_pending_during_maintenance(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        row = MasterclassNotification(
            id="99999999-9999-9999-9999-999999999999",
            user_id="11111111-1111-1111-1111-111111111111",
            notification_kind="recipes_followup",
            deduplication_key="recipes:maintenance",
            due_at=datetime.now(UTC) - timedelta(seconds=1),
            status="pending",
            payload={},
        )
        session.add(row)
        session.commit()
        sender = FakeSender()

        result = dispatch_due_masterclass_notifications(
            session,
            sender,
            "https://example.test/offers",
            lambda *_: {"ACCESS_MASTERCLASS"},
            allowed_telegram_ids="446056103,5677281049",
        )

        assert result["maintenance_filtered"] == 1
        assert row.status == "pending"
        assert sender.sent == []


def test_course_stall_sends_only_for_latest_unfinished_activity(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        user_id = "11111111-1111-1111-1111-111111111111"
        event_id = "44444444-4444-4444-4444-444444444444"
        occurred_at = datetime.now(UTC) - timedelta(hours=73)
        session.execute(
            text(
                "INSERT INTO masterclass_events (id, user_id, event_type, occurred_at) "
                "VALUES (:id, :user_id, 'masterclass_day_opened', :occurred_at)"
            ),
            {"id": event_id, "user_id": user_id, "occurred_at": occurred_at},
        )
        session.add(MasterclassNotification(
            id="55555555-5555-5555-5555-555555555555",
            user_id=user_id,
            event_id=event_id,
            notification_kind="course_stalled_72h",
            content_code="tpl_postpurchase_tempo_late",
            deduplication_key="stall:current",
            due_at=occurred_at + timedelta(hours=72),
            status="pending",
            payload={"day": 3},
        ))
        session.commit()

        sender = FakeSender()
        result = dispatch_due_masterclass_notifications(
            session, sender, "", lambda *_: {"ACCESS_MASTERCLASS"}
        )
        assert result["sent"] == 1
        assert sender.sent[0][1] == "tpl_postpurchase_tempo_late"


def test_course_stall_is_cancelled_by_later_activity(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        user_id = "11111111-1111-1111-1111-111111111111"
        old_event = "66666666-6666-6666-6666-666666666666"
        new_event = "77777777-7777-7777-7777-777777777777"
        occurred_at = datetime.now(UTC) - timedelta(hours=73)
        session.execute(
            text(
                "INSERT INTO masterclass_events (id, user_id, event_type, occurred_at) VALUES "
                "(:old_id, :user_id, 'masterclass_day_opened', :old_at), "
                "(:new_id, :user_id, 'masterclass_article_completed', :new_at)"
            ),
            {
                "old_id": old_event,
                "new_id": new_event,
                "user_id": user_id,
                "old_at": occurred_at,
                "new_at": datetime.now(UTC) - timedelta(hours=1),
            },
        )
        session.add(MasterclassNotification(
            id="88888888-8888-8888-8888-888888888888",
            user_id=user_id,
            event_id=old_event,
            notification_kind="course_stalled_72h",
            content_code="tpl_postpurchase_tempo_late",
            deduplication_key="stall:stale",
            due_at=occurred_at + timedelta(hours=72),
            status="pending",
            payload={"day": 3},
        ))
        session.commit()

        sender = FakeSender()
        result = dispatch_due_masterclass_notifications(
            session, sender, "", lambda *_: {"ACCESS_MASTERCLASS"}
        )
        assert result["skipped"] == 1
        assert sender.sent == []
