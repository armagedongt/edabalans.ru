from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.masterclass_dispatch import (
    client_values,
    dispatch_due_masterclass_notifications,
    telegram_text_parts,
)
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
    session.execute(text(
        "CREATE TABLE IF NOT EXISTS masterclass_day_progress ("
        "user_id TEXT NOT NULL, day_number INTEGER NOT NULL, completed_at DATETIME)"
    ))
    session.execute(text(
        "CREATE TABLE IF NOT EXISTS user_offers ("
        "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, stage_code TEXT NOT NULL, "
        "started_at DATETIME NOT NULL, expires_at DATETIME, status TEXT NOT NULL, "
        "trigger_event_id TEXT)"
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
        "tpl_postpurchase_day_unopened",
        "tpl_postpurchase_final_offer",
    ):
        body = "Откройте {{day_url}}" if code == "tpl_postpurchase_day_unopened" else "Откройте {{offers_url}}"
        session.add(ContentItem(code=code, title=code, body_source=body, status="published"))
    session.flush()
    return contact


def test_client_summary_uses_masterclass_payment_and_human_question_titles(tmp_path):
    with session_factory(tmp_path) as session:
        contact = add_contact_and_content(session)
        for ddl in (
            "CREATE TABLE user_emails (user_id TEXT, email_original TEXT, is_primary BOOLEAN, created_at DATETIME)",
            "CREATE TABLE resources (id TEXT PRIMARY KEY, code TEXT)",
            "CREATE TABLE user_accesses (user_id TEXT, resource_id TEXT, source_payment_id TEXT, revoked_at DATETIME, expires_at DATETIME)",
            "CREATE TABLE products (id TEXT PRIMARY KEY, code TEXT, name TEXT)",
            "CREATE TABLE payments (id TEXT PRIMARY KEY, product_id TEXT, product_name_raw TEXT, paid_at DATETIME, source_event_at DATETIME, created_at DATETIME)",
            "CREATE TABLE questionnaire_runs (id TEXT PRIMARY KEY, user_id TEXT, kind TEXT)",
            "CREATE TABLE questionnaire_answers (run_id TEXT, question_code TEXT, answer_text TEXT, updated_at DATETIME)",
        ):
            session.execute(text(ddl))
        user_id = contact.user_id
        session.execute(text(
            "INSERT INTO user_emails VALUES (:user_id, 'buyer@example.com', 1, CURRENT_TIMESTAMP)"
        ), {"user_id": user_id})
        session.execute(text("INSERT INTO resources VALUES ('mc', 'ACCESS_MASTERCLASS')"))
        session.execute(text("INSERT INTO products VALUES ('mc-product', 'MASTERCLASS_RECIPES', 'Мастер-класс · Стандартный')"))
        session.execute(text(
            "INSERT INTO payments VALUES ('mc-payment', 'mc-product', 'Сырой параметр из платежа', CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP)"
        ))
        session.execute(text(
            "INSERT INTO payments VALUES ('later-payment', NULL, 'Рецепты', CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP)"
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
        assert values["masterclass_tariff"] == "Стандартный"
        assert "Главный запрос" in values["questionnaire_formatted"]
        assert "<b>Главный запрос:</b>" in values["questionnaire_formatted"]
        assert "main_request" not in values["questionnaire_formatted"]


def test_long_telegram_summary_splits_on_paragraphs():
    body = "Заголовок\n\n" + ("ответ " * 900) + "\n\nКонец"
    parts = telegram_text_parts(body)
    assert len(parts) > 1
    assert all(len(part) <= 3900 for part in parts)
    assert "".join("".join(parts).split()) == "".join(body.split())


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


def test_dispatch_skips_legacy_dqs_support_notification(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        row = MasterclassNotification(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            user_id="11111111-1111-1111-1111-111111111111",
            notification_kind="dqs_support",
            content_code="tpl_postpurchase_dqs_support",
            deduplication_key="dqs:legacy",
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
            "",
            lambda *_: {"ACCESS_MASTERCLASS"},
        )

        assert result["skipped"] == 1
        assert row.status == "skipped"
        assert row.error_message == "nothing relevant to send"
        assert sender.sent == []


def test_sales_reminder_is_sent_once_for_its_current_window(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        user_id = "11111111-1111-1111-1111-111111111111"
        event_id = "10101010-1010-1010-1010-101010101010"
        now = datetime.now(UTC)
        session.execute(
            text(
                "INSERT INTO user_offers VALUES "
                "('window-1', :user_id, 'early', :started_at, :expires_at, "
                "'active', :event_id)"
            ),
            {
                "user_id": user_id,
                "started_at": now - timedelta(hours=48, seconds=1),
                "expires_at": now + timedelta(hours=24),
                "event_id": event_id,
            },
        )
        session.add(MasterclassNotification(
            user_id=user_id,
            event_id=event_id,
            notification_kind="sales_last_chance_due",
            content_code="tpl_postpurchase_recipes_missing",
            deduplication_key="offer:early:window-1:last-chance",
            due_at=now - timedelta(seconds=1),
            status="pending",
            payload={"stage": "early"},
        ))
        session.commit()

        sender = FakeSender()
        result = dispatch_due_masterclass_notifications(
            session, sender, "https://example.test/offers", lambda *_: {"ACCESS_MASTERCLASS"}
        )

        assert result["sent"] == 1
        assert len(sender.sent) == 1
        assert dispatch_due_masterclass_notifications(
            session, sender, "https://example.test/offers", lambda *_: {"ACCESS_MASTERCLASS"}
        )["sent"] == 0


def test_sales_reminder_is_revalidated_and_skipped_after_window_purchase(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        user_id = "11111111-1111-1111-1111-111111111111"
        event_id = "20202020-2020-2020-2020-202020202020"
        now = datetime.now(UTC)
        started_at = now - timedelta(hours=48, seconds=1)
        session.execute(
            text(
                "INSERT INTO user_offers VALUES "
                "('window-2', :user_id, 'second', :started_at, :expires_at, "
                "'active', :event_id)"
            ),
            {
                "user_id": user_id,
                "started_at": started_at,
                "expires_at": now + timedelta(hours=24),
                "event_id": event_id,
            },
        )
        session.execute(
            text(
                "INSERT INTO masterclass_events (id, user_id, event_type, occurred_at) "
                "VALUES ('purchase-1', :user_id, 'offer_purchase_confirmed', :occurred_at)"
            ),
            {"user_id": user_id, "occurred_at": started_at + timedelta(hours=1)},
        )
        notification = MasterclassNotification(
            user_id=user_id,
            event_id=event_id,
            notification_kind="sales_last_chance_due",
            content_code="tpl_postpurchase_recipes_missing",
            deduplication_key="offer:second:window-2:last-chance",
            due_at=now - timedelta(seconds=1),
            status="pending",
            payload={"stage": "second"},
        )
        session.add(notification)
        session.commit()

        sender = FakeSender()
        result = dispatch_due_masterclass_notifications(
            session, sender, "https://example.test/offers", lambda *_: {"ACCESS_MASTERCLASS"}
        )

        assert result["skipped"] == 1
        assert notification.status == "skipped"
        assert notification.error_message == "offer window expired, changed, or was purchased"
        assert sender.sent == []


def test_sales_reminder_is_skipped_when_masterclass_access_was_revoked(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        user_id = "11111111-1111-1111-1111-111111111111"
        event_id = "30303030-3030-3030-3030-303030303030"
        now = datetime.now(UTC)
        session.execute(
            text(
                "INSERT INTO user_offers VALUES "
                "('window-3', :user_id, 'review', :started_at, :expires_at, "
                "'active', :event_id)"
            ),
            {
                "user_id": user_id,
                "started_at": now - timedelta(hours=48, seconds=1),
                "expires_at": now + timedelta(hours=24),
                "event_id": event_id,
            },
        )
        notification = MasterclassNotification(
            user_id=user_id,
            event_id=event_id,
            notification_kind="sales_last_chance_due",
            content_code="tpl_postpurchase_review_no_consultation",
            deduplication_key="offer:review:window-3:last-chance",
            due_at=now - timedelta(seconds=1),
            status="pending",
            payload={"stage": "review"},
        )
        session.add(notification)
        session.commit()

        sender = FakeSender()
        result = dispatch_due_masterclass_notifications(
            session, sender, "https://example.test/offers", lambda *_: set()
        )

        assert result["skipped"] == 1
        assert notification.status == "skipped"
        assert notification.error_message == "masterclass access is no longer active"
        assert sender.sent == []


def test_review_sales_due_is_skipped_when_storefront_has_no_offer(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        user_id = "11111111-1111-1111-1111-111111111111"
        event_id = "40404040-4040-4040-4040-404040404040"
        now = datetime.now(UTC)
        session.execute(
            text(
                "INSERT INTO user_offers VALUES "
                "('window-4', :user_id, 'review', :started_at, :expires_at, "
                "'active', :event_id)"
            ),
            {
                "user_id": user_id,
                "started_at": now - timedelta(hours=48, seconds=1),
                "expires_at": now + timedelta(hours=24),
                "event_id": event_id,
            },
        )
        notification = MasterclassNotification(
            user_id=user_id,
            event_id=event_id,
            notification_kind="sales_last_chance_due",
            deduplication_key="offer:review:window-4:last-chance",
            due_at=now - timedelta(seconds=1),
            status="pending",
            payload={"stage": "review"},
        )
        session.add(notification)
        session.commit()

        access = {
            "ACCESS_MASTERCLASS",
            "ACCESS_RECIPES",
            "ACCESS_CALORIES",
            "ACCESS_STRENGTH",
            "ACCESS_CONSULTATION",
        }
        sender = FakeSender()
        result = dispatch_due_masterclass_notifications(
            session, sender, "https://example.test/offers", lambda *_: access
        )

        assert result["skipped"] == 1
        assert notification.error_message == "nothing relevant to send"
        assert sender.sent == []


def test_unopened_day_reminder_sends_once_only_while_target_is_unopened(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        user_id = "11111111-1111-1111-1111-111111111111"
        session.execute(
            text("INSERT INTO masterclass_day_progress VALUES (:user_id, 1, CURRENT_TIMESTAMP)"),
            {"user_id": user_id},
        )
        notification = MasterclassNotification(
            id="abababab-abab-abab-abab-abababababab",
            user_id=user_id,
            notification_kind="course_day_unopened_18h",
            content_code="tpl_postpurchase_day_unopened",
            deduplication_key="day:2:18h",
            due_at=datetime.now(UTC) - timedelta(seconds=1),
            status="pending",
            payload={"day": 2, "day_title": "Диеты — разные инструменты", "unlock_at": (datetime.now(UTC) - timedelta(hours=12)).isoformat()},
        )
        session.add(notification)
        session.commit()

        sender = FakeSender()
        result = dispatch_due_masterclass_notifications(
            session,
            sender,
            "",
            lambda *_: {"ACCESS_MASTERCLASS"},
            course_url="https://example.test/lk",
        )
        assert result["sent"] == 1
        assert "course_day=2" in sender.sent[0][2]
        assert dispatch_due_masterclass_notifications(
            session, sender, "", lambda *_: {"ACCESS_MASTERCLASS"}
        )["sent"] == 0


def test_unopened_day_reminder_is_skipped_after_target_day_was_opened(tmp_path):
    with session_factory(tmp_path) as session:
        add_contact_and_content(session)
        user_id = "11111111-1111-1111-1111-111111111111"
        session.execute(
            text("INSERT INTO masterclass_day_progress VALUES (:user_id, 1, CURRENT_TIMESTAMP)"),
            {"user_id": user_id},
        )
        session.execute(
            text("INSERT INTO masterclass_day_progress VALUES (:user_id, 2, NULL)"),
            {"user_id": user_id},
        )
        session.add(MasterclassNotification(
            user_id=user_id,
            notification_kind="course_day_unopened_18h",
            content_code="tpl_postpurchase_day_unopened",
            deduplication_key="day:2:opened",
            due_at=datetime.now(UTC) - timedelta(seconds=1),
            status="pending",
            payload={"day": 2, "day_title": "День 2"},
        ))
        session.commit()
        sender = FakeSender()
        result = dispatch_due_masterclass_notifications(
            session, sender, "", lambda *_: {"ACCESS_MASTERCLASS"}
        )
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
