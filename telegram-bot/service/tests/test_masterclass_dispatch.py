from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.masterclass_dispatch import dispatch_due_masterclass_notifications
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
    return Session(engine)


def add_contact_and_content(session):
    bot = BotInstance(code="test", username="test", display_name="test", token_env_name="TOKEN", is_active=True)
    session.add(bot); session.flush()
    contact = Contact(bot_instance_id=bot.id, user_id="11111111-1111-1111-1111-111111111111", telegram_user_id="42", chat_id="42", status="active")
    session.add(contact)
    for code in ("tpl_postpurchase_recipes_missing", "tpl_postpurchase_recipes_owned", "tpl_postpurchase_review_consultation"):
        session.add(ContentItem(code=code, title=code, body_source="Откройте {{offers_url}}", status="draft"))
    session.flush()
    return contact


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
        result = dispatch_due_masterclass_notifications(session, sender, "", lambda *_: {"ACCESS_RECIPES", "ACCESS_CALORIES", "ACCESS_STRENGTH", "ACCESS_CONSULTATION_RECORDINGS"})
        assert result["skipped"] == 1
        assert sender.sent == []
