from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.engine import advance_run, resume_callback, start_run
from app.models import BotInstance, BotRoute, Contact, ContentItem, Sequence, SequenceEdge, SequenceRun, SequenceStep, SequenceVersion, StepDelivery, UserVariable
from app.seed import POSTPURCHASE_CODE, PREPURCHASE_CODE, seed_defaults


class FakeSender:
    def __init__(self):
        self.sent = []

    def send_content(self, chat_id, content, configuration):
        self.sent.append((chat_id, content.code, configuration))
        return str(len(self.sent))


def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'service.sqlite'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_seed_contains_exactly_30_message_slots(tmp_path):
    with session_factory(tmp_path) as session:
        result = seed_defaults(session, "TetrisgfgfgfBot")
        assert result == {"messages": 30, "sequences": 2}
        pre = session.scalar(select(Sequence).where(Sequence.code == PREPURCHASE_CODE))
        version = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == pre.id))
        message_count = session.scalar(select(func.count(SequenceStep.id)).where(SequenceStep.sequence_version_id == version.id, SequenceStep.kind.in_(["MESSAGE", "VIDEO_NOTE"])))
        assert message_count == 30
        assert session.scalar(select(func.count(ContentItem.id))) == 46
        assert "Навигация!" in session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_navigation_pin"))
        assert "Сделайте похудение проще" in session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_welcome_offer"))
        assert session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_has_masterclass")).startswith("Привет! У вас уже есть мой Мастер-класс")
        assert "{{next_message_at}}" in session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_intensive_waiting"))
        assert "похудение-это-есть.рф/intensiv" in session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_intensive_complete"))
        assert session.scalar(select(func.count(SequenceEdge.id))) > 0
        assert session.scalar(select(BotRoute.target_sequence_code).where(BotRoute.code == "main_start")) == PREPURCHASE_CODE


def test_seed_adds_editable_disabled_postpurchase_module(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        post = session.scalar(select(Sequence).where(Sequence.code == POSTPURCHASE_CODE))
        assert post.status == "disabled"
        version = session.scalar(
            select(SequenceVersion)
            .where(SequenceVersion.sequence_id == post.id)
            .order_by(SequenceVersion.version_no.desc())
        )
        assert version.status == "draft"
        steps = list(session.scalars(
            select(SequenceStep)
            .where(SequenceStep.sequence_version_id == version.id)
            .order_by(SequenceStep.position)
        ))
        assert len(steps) == 14
        assert steps[0].step_key == "pp_identity"
        assert steps[-1].kind == "STOP"
        assert any(step.delay_seconds == 21600 for step in steps)
        assert any(step.delay_seconds == 3600 for step in steps)
        assert session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_postpurchase_questionnaire")).find("{{questionnaire_formatted}}") >= 0

        # Re-running seed must not create another draft version or duplicate slots.
        seed_defaults(session, "TetrisgfgfgfBot")
        assert session.scalar(select(func.count(SequenceVersion.id)).where(SequenceVersion.sequence_id == post.id)) == 2


def test_start_is_idempotent_and_waits_for_button(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        bot = session.scalar(select(BotInstance))
        contact = Contact(bot_instance_id=bot.id, telegram_user_id="42", chat_id="42")
        session.add(contact); session.commit()
        run = start_run(session, contact.id, PREPURCHASE_CODE)
        assert start_run(session, contact.id, PREPURCHASE_CODE).id == run.id
        sender = FakeSender()
        advance_run(session, run, sender)
        assert [item[1] for item in sender.sent] == ["tpl_entry_circle", "tpl_entry_welcome"]
        assert run.status == "waiting"
        assert resume_callback(session, contact.id, "wrong") is None
        resumed = resume_callback(session, contact.id, "start_intensive")
        assert resumed.status == "active"


def test_purchase_stops_presale_at_disabled_branch(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        bot = session.scalar(select(BotInstance))
        contact = Contact(bot_instance_id=bot.id, telegram_user_id="77", chat_id="77")
        session.add(contact); session.flush()
        session.add(UserVariable(contact_id=contact.id, key="has_product:masterclass", value={"value": True}))
        session.commit()
        run = start_run(session, contact.id, PREPURCHASE_CODE)
        sender = FakeSender(); advance_run(session, run, sender)
        resume_callback(session, contact.id, "start_intensive")
        # First pass crosses the zero delay; the next processes the product check.
        advance_run(session, run, sender); advance_run(session, run, sender)
        assert run.status == "branch_pending"
        assert run.context["pending_sequence"] == "postpurchase_masterclass"
        assert session.scalar(select(func.count(StepDelivery.id)).where(StepDelivery.run_id == run.id)) == 2
