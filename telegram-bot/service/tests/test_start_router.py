from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.engine import advance_run, start_run
from app.models import BotInstance, Contact, ManualMessage, SequenceRun, StepDelivery, TrackingEvent, UserVariable
from app.seed import START_ENTRY_CODE, WELCOME_CODE, seed_defaults
from app.start_router import StartDecision, StartFacts, decision_from_facts, execute_start_decision, inspect_start


class FakeSender:
    def __init__(self):
        self.sent = []

    def send_content(self, chat_id, content, configuration):
        self.sent.append((chat_id, content.code, content.body_source))
        return str(len(self.sent))


def prepared(tmp_path, suffix: str = ""):
    engine = make_engine(f"sqlite:///{tmp_path / ('router' + suffix + '.sqlite')}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_defaults(session, "TetrisgfgfgfBot")
    bot = session.scalar(select(BotInstance))
    contact = Contact(bot_instance_id=bot.id, telegram_user_id=f"42{suffix}", chat_id=f"42{suffix}")
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
    assert decide(welcome_ever_started=True).code == "welcome_state_error"
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
        execute_start_decision(session, contact, decision, current, sender, START_ENTRY_CODE, update_id="buyer-1")
        session.commit()
        assert decision.code == "masterclass_owned"
        assert run.status == "completed"
        assert run.context["stopped_reason"] == "masterclass_owned"
        assert sender.sent[0][1] == "tpl_start_has_masterclass"
        assert session.scalar(select(ManualMessage.status)) == "sent"
    finally:
        session.close()


def test_lost_welcome_state_is_logged_without_message(tmp_path):
    session, contact = prepared(tmp_path, "error")
    try:
        run = start_run(session, contact.id, START_ENTRY_CODE)
        run.status = "completed"
        session.commit()
        _, decision, current = inspect_start(session, contact, False)
        sender = FakeSender()
        execute_start_decision(session, contact, decision, current, sender, START_ENTRY_CODE, update_id="error-1")
        session.commit()
        assert decision.code == "welcome_state_error"
        assert sender.sent == []
        event = session.scalar(select(TrackingEvent).where(TrackingEvent.event_type == "start_routing_error"))
        assert event.metadata_json["reason"] == "welcome_started_without_run_or_day_four"
    finally:
        session.close()
