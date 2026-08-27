from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.engine import advance_run, resume_callback, resume_wait_timeout, start_run
from app.graph import graph_issues
from app.models import BotInstance, BotRoute, Contact, ContentItem, CrmMessengerAccount, CrmTag, CrmUser, CrmUserTag, Sequence, SequenceEdge, SequenceRun, SequenceStep, SequenceVersion, StepDelivery, TrackingEvent, UserVariable
from app.seed import POSTPURCHASE_CODE, PREPURCHASE_CODE, WELCOME_CODE, seed_defaults


class FakeSender:
    def __init__(self, fail_pin=False, subscription=None):
        self.sent = []
        self.pinned = []
        self.fail_pin = fail_pin
        self.subscription = subscription

    def send_content(self, chat_id, content, configuration):
        self.sent.append((chat_id, content.code, configuration))
        return str(len(self.sent))

    def pin_message(self, chat_id, message_id):
        if self.fail_pin:
            raise RuntimeError("pin is unavailable")
        self.pinned.append((chat_id, message_id))

    def subscription_status(self, user_id):
        return self.subscription


def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'service.sqlite'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_seed_splits_start_welcome_and_nurture_modules(tmp_path):
    with session_factory(tmp_path) as session:
        result = seed_defaults(session, "TetrisgfgfgfBot")
        assert result == {"messages": 30, "sequences": 4}
        counts = {}
        for code in (WELCOME_CODE, PREPURCHASE_CODE):
            sequence = session.scalar(select(Sequence).where(Sequence.code == code))
            version = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == sequence.id))
            counts[code] = session.scalar(select(func.count(SequenceStep.id)).where(SequenceStep.sequence_version_id == version.id, SequenceStep.kind.in_(["MESSAGE", "VIDEO_NOTE"])))
        assert counts == {WELCOME_CODE: 12, PREPURCHASE_CODE: 17}
        assert session.scalar(select(func.count(ContentItem.id))) == 55
        day_unopened_content = session.scalar(
            select(ContentItem).where(ContentItem.code == "tpl_postpurchase_day_unopened")
        )
        assert day_unopened_content is not None
        maintenance = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_maintenance_notice"))
        assert maintenance.status == "published"
        assert "@FitnessSergey" in maintenance.body_source
        assert "Навигация!" in session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_navigation_pin"))
        assert "Сделайте похудение проще" in session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_welcome_offer"))
        assert "похудение-это-есть.рф/intensiv" not in session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_welcome_offer"))
        circle = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_entry_circle"))
        assert circle.media_kind == "video_note"
        assert circle.media_path == "/app/media/welcome-intro-circle.mp4"
        navigation_step = session.scalar(select(SequenceStep).where(SequenceStep.step_key == "welcome_navigation"))
        assert navigation_step.configuration["pin_after_send"] is True
        assert navigation_step.configuration["buttons"][0]["url"] == "https://t.me/Fitness_Talks"
        assert session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_has_masterclass")).startswith("Привет! У вас уже есть мой Мастер-класс")
        waiting = session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_intensive_waiting"))
        assert waiting.startswith("Посты интенсива приходят вам по расписанию")
        assert "{{next_message_at}}" in waiting
        complete = session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_intensive_complete"))
        assert complete.startswith("<b>Сделайте похудение проще</b>")
        assert complete.count("похудение-это-есть.рф/intensiv#rec") == 4
        assert session.scalar(select(func.count(SequenceEdge.id))) > 0
        assert session.scalar(select(BotRoute.target_sequence_code).where(BotRoute.code == "main_start")) == WELCOME_CODE


def test_seed_upgrades_intermediate_combined_layout_with_new_versions(tmp_path):
    with session_factory(tmp_path) as session:
        welcome = Sequence(code=WELCOME_CODE, name="old welcome", description="old", status="published")
        nurture = Sequence(code=PREPURCHASE_CODE, name="old nurture", description="old", status="published")
        session.add_all([welcome, nurture]); session.flush()
        old_welcome = SequenceVersion(sequence_id=welcome.id, version_no=1, status="published")
        old_nurture = SequenceVersion(sequence_id=nurture.id, version_no=1, status="published")
        session.add_all([old_welcome, old_nurture]); session.flush()
        session.add(SequenceStep(sequence_version_id=old_welcome.id, step_key="welcome_day1", position=1, kind="STOP", label="old"))
        session.add(SequenceStep(sequence_version_id=old_nurture.id, step_key="nurture_delay_hard_sale_1", position=1, kind="DELAY", label="old delay", delay_seconds=43200))
        session.commit()

        seed_defaults(session, "TetrisgfgfgfBot")

        latest_welcome = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == welcome.id).order_by(SequenceVersion.version_no.desc()))
        latest_nurture = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == nurture.id).order_by(SequenceVersion.version_no.desc()))
        assert latest_welcome.version_no == 2
        assert session.scalar(select(SequenceStep.id).where(SequenceStep.sequence_version_id == latest_welcome.id, SequenceStep.step_key == "welcome_navigation"))
        assert latest_nurture.version_no == 2
        assert session.scalar(select(SequenceStep.id).where(SequenceStep.sequence_version_id == latest_nurture.id, SequenceStep.step_key == "nurture_delay_hard_sale_1")) is None


def test_seed_publishes_new_welcome_version_when_channel_check_is_enabled(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        welcome = session.scalar(select(Sequence).where(Sequence.code == WELCOME_CODE))
        first = session.scalar(
            select(SequenceVersion)
            .where(SequenceVersion.sequence_id == welcome.id, SequenceVersion.status == "published")
        )

        seed_defaults(
            session,
            "Fitness_Talks_bot",
            enable_subscription_checks=True,
        )

        latest = session.scalar(
            select(SequenceVersion)
            .where(SequenceVersion.sequence_id == welcome.id, SequenceVersion.status == "published")
            .order_by(SequenceVersion.version_no.desc())
        )
        assert latest.version_no == first.version_no + 1
        assert first.status == "archived"
        checks = session.scalars(
            select(SequenceStep).where(
                SequenceStep.sequence_version_id == latest.id,
                SequenceStep.kind == "CONDITION",
            )
        ).all()
        assert checks
        assert all(step.configuration["enabled"] is True for step in checks)

        seed_defaults(
            session,
            "Fitness_Talks_bot",
            enable_subscription_checks=True,
        )
        assert session.scalar(
            select(func.count(SequenceVersion.id)).where(SequenceVersion.sequence_id == welcome.id)
        ) == 2


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
        assert len(steps) == 15
        day_unopened_content = session.scalar(
            select(ContentItem).where(ContentItem.code == "tpl_postpurchase_day_unopened")
        )
        assert day_unopened_content is not None
        day_unopened_step = next(step for step in steps if step.step_key == "pp_day_unopened_18h")
        assert day_unopened_step.content_item_id == day_unopened_content.id
        assert day_unopened_step.configuration["trigger"] == "course_day_unopened_18h"
        assert steps[0].step_key == "pp_identity"
        assert steps[-1].kind == "STOP"
        assert any(step.step_key == "pp_course_stalled_72h" for step in steps)
        assert any(step.step_key == "pp_current_diet_questionnaire" for step in steps)
        assert any(step.step_key == "pp_dqs_app_link" for step in steps)
        assert any(step.step_key == "pp_review_week_day7" for step in steps)
        assert any(
            (step.configuration or {}).get("trigger") == "sales_last_chance_due"
            for step in steps
        )
        assert all(step.delay_seconds is None for step in steps)
        assert session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_postpurchase_identity")).find("{{questionnaire_formatted}}") >= 0
        assert "{{questionnaire_formatted}}" not in session.scalar(
            select(ContentItem.body_source).where(ContentItem.code == "tpl_postpurchase_questionnaire")
        )
        assert "{{current_diet_formatted}}" in session.scalar(
            select(ContentItem.body_source).where(ContentItem.code == "tpl_postpurchase_current_diet")
        )

        # Re-running seed must not create another draft version or duplicate slots.
        seed_defaults(session, "TetrisgfgfgfBot")
        assert session.scalar(select(func.count(SequenceVersion.id)).where(SequenceVersion.sequence_id == post.id)) == 2


def test_start_is_idempotent_and_waits_for_button(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        bot = session.scalar(select(BotInstance))
        contact = Contact(bot_instance_id=bot.id, telegram_user_id="42", chat_id="42")
        session.add(contact); session.commit()
        run = start_run(session, contact.id, WELCOME_CODE)
        assert start_run(session, contact.id, WELCOME_CODE).id == run.id
        sender = FakeSender()
        advance_run(session, run, sender)
        assert [item[1] for item in sender.sent] == ["tpl_start_navigation_pin", "tpl_entry_circle", "tpl_start_welcome_offer"]
        assert sender.pinned == [("42", "1")]
        assert run.status == "waiting"
        assert resume_callback(session, contact.id, "wrong") is None
        resumed = resume_callback(session, contact.id, "start_intensive")
        assert resumed.status == "active"


def test_pin_error_does_not_stop_welcome(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        bot = session.scalar(select(BotInstance))
        contact = Contact(bot_instance_id=bot.id, telegram_user_id="pin", chat_id="pin")
        session.add(contact); session.commit()
        run = start_run(session, contact.id, WELCOME_CODE)
        advance_run(session, run, FakeSender(fail_pin=True))
        assert run.status == "waiting"
        delivery = session.scalar(select(StepDelivery).where(StepDelivery.step_key == "welcome_navigation"))
        assert delivery.status == "sent"
        assert delivery.payload_snapshot["pin_error"] == "pin is unavailable"


def test_subscription_failure_retries_and_fails_open_to_day1(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        day1 = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_day1"))
        day1.status = "published"; day1.editorial_status = "approved"
        for step in session.scalars(select(SequenceStep).where(SequenceStep.step_key.in_(["welcome_subscription", "welcome_subscription_recheck"]))):
            step.configuration = {**step.configuration, "enabled": True}
        bot = session.scalar(select(BotInstance))
        contact = Contact(bot_instance_id=bot.id, telegram_user_id="sub", chat_id="sub")
        session.add(contact); session.commit()
        run = start_run(session, contact.id, WELCOME_CODE)
        sender = FakeSender(subscription=False)
        advance_run(session, run, sender)
        resume_callback(session, contact.id, "start_intensive")
        advance_run(session, run, sender)
        assert sender.sent[-1][1] == "tpl_start_subscription_reminder"
        assert run.status == "waiting"
        assert run.context["waiting_callback"] == "check_subscription"

        # A retry has its own visible prompt, then waits on the same callback.
        resume_callback(session, contact.id, "check_subscription")
        advance_run(session, run, sender)
        assert run.status == "waiting"
        assert sender.sent[-1][1] == "tpl_start_subscription_retry_reminder"

        # The repeated prompt still rechecks the channel; it cannot skip to Day 1.
        resume_callback(session, contact.id, "check_subscription")
        advance_run(session, run, sender)
        assert run.status == "waiting"
        assert sender.sent[-1][1] == "tpl_start_subscription_retry_reminder"

        # Five minutes from the first prompt is fail-open: Day 1 arrives directly.
        run.next_action_at = datetime.now(UTC) - timedelta(seconds=1)
        resume_wait_timeout(session, run)
        advance_run(session, run, sender)
        assert sender.sent[-1][1] == "tpl_day1"
        assert "tpl_subscription_passed" not in [item[1] for item in sender.sent]
        assert "tpl_subscription_fail_open" not in [item[1] for item in sender.sent]
        outcomes = list(session.scalars(select(TrackingEvent.event_type).where(TrackingEvent.contact_id == contact.id)))
        assert outcomes.count("subscription_check") >= 3
        assert "subscription_fail_open" in outcomes


def test_real_subscription_check_updates_account_and_canonical_tag(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(
            session,
            "Fitness_Talks_bot",
            enable_subscription_checks=True,
        )
        bot = session.scalar(select(BotInstance))
        user_id = "11111111-1111-1111-1111-111111111111"
        user = CrmUser(id=user_id, display_name="Owner")
        tags = [
            CrmTag(code="subscription_yes", name="Подписан", category="subscription"),
            CrmTag(code="subscription_no", name="Не подписан", category="subscription"),
            CrmTag(code="subscription_left", name="Отписался", category="subscription"),
        ]
        session.add_all([user, *tags]); session.flush()
        account = CrmMessengerAccount(
            user_id=user_id,
            platform="telegram",
            platform_user_id="subscribed-before",
            subscription_status="subscribed",
        )
        contact = Contact(
            bot_instance_id=bot.id,
            user_id=user_id,
            telegram_user_id="subscribed-before",
            chat_id="subscribed-before",
        )
        session.add_all([account, contact]); session.flush()
        session.add(CrmUserTag(user_id=user_id, tag_id=tags[0].id, source="test"))
        session.commit()

        run = start_run(session, contact.id, WELCOME_CODE)
        sender = FakeSender(subscription=False)
        advance_run(session, run, sender)
        resume_callback(session, contact.id, "start_intensive")
        advance_run(session, run, sender)

        assert account.subscription_status == "not_subscribed"
        names = list(session.scalars(
            select(CrmTag.name)
            .join(CrmUserTag, CrmUserTag.tag_id == CrmTag.id)
            .where(CrmUserTag.user_id == user_id)
        ))
        assert names == ["Отписался"]


def test_welcome_does_not_check_purchase(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        day1 = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_day1"))
        day1.status = "published"; day1.editorial_status = "approved"
        bot = session.scalar(select(BotInstance))
        contact = Contact(bot_instance_id=bot.id, telegram_user_id="77", chat_id="77")
        session.add(contact); session.flush()
        session.add(UserVariable(contact_id=contact.id, key="has_product:masterclass", value={"value": True}))
        session.commit()
        run = start_run(session, contact.id, WELCOME_CODE)
        sender = FakeSender(); advance_run(session, run, sender)
        resume_callback(session, contact.id, "start_intensive")
        advance_run(session, run, sender)
        assert sender.sent[-1][1] == "tpl_day1"
        assert run.status == "active"
        version = session.get(SequenceVersion, run.sequence_version_id)
        welcome_steps = session.scalars(select(SequenceStep).where(SequenceStep.sequence_version_id == version.id)).all()
        assert not any(step.configuration.get("condition") == "has_product" for step in welcome_steps)


def test_sequence_stops_before_unapproved_message(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        bot = session.scalar(select(BotInstance))
        contact = Contact(bot_instance_id=bot.id, telegram_user_id="draft", chat_id="draft")
        session.add(contact); session.commit()
        run = start_run(session, contact.id, WELCOME_CODE)
        sender = FakeSender()
        advance_run(session, run, sender)
        resume_callback(session, contact.id, "start_intensive")
        advance_run(session, run, sender)

        assert run.status == "error"
        assert run.last_error == "Content is not owner-approved: tpl_day1"
        assert "tpl_day1" not in [item[1] for item in sender.sent]


def test_welcome_timing_and_subscription_observation_steps(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        sequence = session.scalar(select(Sequence).where(Sequence.code == WELCOME_CODE))
        version = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == sequence.id).order_by(SequenceVersion.version_no.desc()))
        steps = {step.step_key: step for step in session.scalars(select(SequenceStep).where(SequenceStep.sequence_version_id == version.id))}
        assert steps["welcome_delay_mid1"].delay_seconds == 11 * 3600
        for key in ("welcome_delay_day2", "welcome_delay_mid2", "welcome_delay_day3", "welcome_delay_mid3", "welcome_delay_day4", "welcome_delay_exit"):
            assert steps[key].delay_seconds == 12 * 3600
        stages = {step.configuration.get("stage") for step in steps.values() if step.configuration.get("condition") == "subscription_check"}
        assert {"before_day1", "after_prompt", "after_day1", "after_mid1", "after_day2", "after_mid2", "after_day3", "after_mid3", "after_day4"} <= stages
        timeout_edge = session.scalar(select(SequenceEdge).where(
            SequenceEdge.sequence_version_id == version.id,
            SequenceEdge.from_step_key == "welcome_subscription_retry_wait",
            SequenceEdge.branch_key == "timeout",
        ))
        assert timeout_edge.to_step_key == "welcome_day1"
        assert not [issue for issue in graph_issues(session, version) if issue["severity"] == "error"]
