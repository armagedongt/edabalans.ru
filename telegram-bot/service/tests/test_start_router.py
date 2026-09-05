from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.engine import advance_run, start_run
from app.models import BotInstance, Contact, ContentItem, CrmUser, ManualMessage, MessengerLinkToken, SequenceRun, StepDelivery, TrackingEvent, UserVariable
from app.seed import WELCOME_CODE, seed_defaults
from app.start_router import StartDecision, StartFacts, decision_from_facts, execute_start_decision, inspect_start, send_system_content


class FakeSender:
    def __init__(self):
        self.sent = []

    def send_content(self, chat_id, content, configuration):
        self.sent.append((chat_id, content.code, content.body_source, configuration))
        return str(len(self.sent))


def prepared(tmp_path, suffix: str = ""):
    engine = make_engine(f"sqlite:///{tmp_path / ('router' + suffix + '.sqlite')}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_defaults(session, "TetrisgfgfgfBot")
    bot = session.scalar(select(BotInstance))
    user = CrmUser(display_name="Получатель", status="active", data_origin="native")
    session.add(user)
    session.flush()
    contact = Contact(bot_instance_id=bot.id, user_id=user.id, telegram_user_id=f"42{suffix}", chat_id=f"42{suffix}")
    session.add(contact)
    session.commit()
    return session, contact


def test_pure_router_covers_every_exit():
    def decide(**overrides) -> StartDecision:
        values = dict(is_first_visit=False, has_masterclass=False, day_four_sent=False, has_active_welcome_run=False, welcome_ever_started=False)
        values.update(overrides)
        return decision_from_facts(StartFacts(**values))

    assert decide(has_masterclass=True).code == "masterclass_owned"
    assert decide(is_first_visit=True).code == "launch_welcome"
    assert decide(day_four_sent=True).code == "intensive_complete"
    assert decide(has_active_welcome_run=True).code == "intensive_waiting"
    assert decide(welcome_ever_started=False).code == "launch_welcome"
    assert decide(welcome_ever_started=True).code == "legacy_update"
    assert decide(has_masterclass=True, day_four_sent=True).code == "masterclass_owned"


def test_router_reads_current_welcome_state(tmp_path):
    session, contact = prepared(tmp_path)
    try:
        facts, decision, _ = inspect_start(session, contact, False)
        assert facts.welcome_ever_started is False
        assert decision.code == "launch_welcome"

        run = start_run(session, contact.id, WELCOME_CODE)
        sender = FakeSender()
        advance_run(session, run, sender)
        facts, decision, current = inspect_start(session, contact, False)
        assert facts.has_active_welcome_run is True
        assert current.id == run.id
        assert decision.code == "intensive_waiting"

        session.add(StepDelivery(run_id=run.id, step_key="welcome_day4", idempotency_key=f"{run.id}:welcome_day4:test", status="sent"))
        session.commit()
        _, decision, _ = inspect_start(session, contact, False)
        assert decision.code == "intensive_complete"
    finally:
        session.close()


def test_buyer_stops_presale_and_gets_editable_template(tmp_path):
    session, contact = prepared(tmp_path, "buyer")
    try:
        run = start_run(session, contact.id, WELCOME_CODE)
        session.add(UserVariable(contact_id=contact.id, key="has_product:masterclass", value={"value": True}))
        session.commit()
        _, decision, current = inspect_start(session, contact, False)
        sender = FakeSender()
        execute_start_decision(session, contact, decision, current, sender, WELCOME_CODE, update_id="buyer-1")
        session.commit()
        assert decision.code == "masterclass_owned"
        assert run.status == "completed"
        assert run.context["stopped_reason"] == "masterclass_owned"
        assert sender.sent[0][1] == "tpl_start_masterclass_owned"
        assert session.scalar(select(ManualMessage.status)) == "sent"
    finally:
        session.close()


def test_lost_welcome_state_gets_legacy_open_intensive_message(tmp_path):
    session, contact = prepared(tmp_path, "error")
    try:
        run = start_run(session, contact.id, WELCOME_CODE)
        run.status = "completed"
        session.commit()
        _, decision, current = inspect_start(session, contact, False)
        sender = FakeSender()
        execute_start_decision(session, contact, decision, current, sender, WELCOME_CODE, update_id="error-1")
        session.commit()
        assert decision.code == "legacy_update"
        assert sender.sent[0][1] == "tpl_intensive_entry_legacy_update"
        assert "{{personal_" not in sender.sent[0][2]
    finally:
        session.close()


def test_first_visit_sends_circle_and_selected_personal_entry_then_starts_schedule(tmp_path):
    session, contact = prepared(tmp_path, "launch")
    try:
        decision = decision_from_facts(StartFacts(
            is_first_visit=True,
            has_masterclass=False,
            day_four_sent=False,
            has_active_welcome_run=False,
            welcome_ever_started=False,
        ))
        sender = FakeSender()

        run = execute_start_decision(
            session,
            contact,
            decision,
            None,
            sender,
            WELCOME_CODE,
            entry_content_code="tpl_intensive_entry_yandex",
        )

        assert run is not None
        assert [item[1] for item in sender.sent] == [
            "tpl_entry_circle",
            "tpl_intensive_entry_yandex",
        ]
        assert "{{personal_" not in sender.sent[1][2]
        assert "/i/" in sender.sent[1][3]["buttons"][0]["url"]
    finally:
        session.close()


def test_system_content_resolves_personal_link(tmp_path):
    session, contact = prepared(tmp_path, "personal")
    try:
        user = CrmUser(display_name="Получатель", status="active", data_origin="native")
        session.add(user)
        session.flush()
        contact.user_id = user.id
        item = session.scalar(
            select(ContentItem).where(ContentItem.code == "tpl_start_intensive_complete")
        )
        item.body_source = "Ваш интенсив: {{personal_intensive_url}}"
        session.commit()

        sender = FakeSender()
        send_system_content(session, contact, item.code, sender)

        assert "{{personal_" not in sender.sent[0][2]
        assert "/i/" in sender.sent[0][2]
        assert session.query(MessengerLinkToken).count() == 1
    finally:
        session.close()
