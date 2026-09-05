from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.engine import advance_run, personalized_delivery, resume_callback, resume_wait_timeout, start_run
from app.graph import graph_issues
from app.models import BotInstance, BotRoute, Contact, ContentItem, CrmMessengerAccount, CrmTag, CrmUser, CrmUserTag, Sequence, SequenceEdge, SequenceRun, SequenceStep, SequenceVersion, StepDelivery, TrackingEvent, UserVariable
from app.seed import POSTPURCHASE_CODE, PREPURCHASE_CODE, WELCOME_CODE, seed_defaults


class FakeSender:
    def __init__(self, fail_pin=False, subscription=None):
        self.sent = []
        self.bodies = []
        self.pinned = []
        self.fail_pin = fail_pin
        self.subscription = subscription

    def send_content(self, chat_id, content, configuration):
        self.sent.append((chat_id, content.code, configuration))
        self.bodies.append(content.body_source or "")
        return str(len(self.sent))

    def pin_message(self, chat_id, message_id):
        if self.fail_pin:
            raise RuntimeError("pin is unavailable")
        self.pinned.append((chat_id, message_id))

    def subscription_status(self, user_id):
        return self.subscription


def test_personalized_delivery_resolves_body_and_button_with_same_code(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        bot = session.scalar(select(BotInstance))
        user = CrmUser(display_name="Получатель", status="active", data_origin="native")
        session.add(user)
        session.flush()
        contact = Contact(
            bot_instance_id=bot.id,
            user_id=user.id,
            telegram_user_id="personal-links",
            chat_id="personal-links",
        )
        content = ContentItem(
            code="tpl_personal_links",
            title="Personal links",
            body_source="Интенсив: {{personal_intensive_url}}",
            source_format="telegram_html",
            status="published",
            editorial_status="approved",
        )

        rendered, configuration = personalized_delivery(
            session,
            contact,
            content,
            {"buttons": [{"text": "Мастер-класс", "url": "{{personal_masterclass_url}}"}]},
        )

        assert "{{personal_" not in rendered.body_source
        assert "{{personal_" not in str(configuration)
        intensive_code = rendered.body_source.rsplit("/", 1)[-1]
        masterclass_code = configuration["buttons"][0]["url"].rsplit("/", 1)[-1]
        assert intensive_code == masterclass_code
        assert len(intensive_code) == 9


def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'service.sqlite'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_seed_splits_start_welcome_and_nurture_modules(tmp_path):
    with session_factory(tmp_path) as session:
        result = seed_defaults(session, "TetrisgfgfgfBot")
        assert result == {"messages": 50, "sequences": 4}
        counts = {}
        for code in (WELCOME_CODE, PREPURCHASE_CODE):
            sequence = session.scalar(select(Sequence).where(Sequence.code == code))
            version = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == sequence.id))
            counts[code] = session.scalar(select(func.count(SequenceStep.id)).where(SequenceStep.sequence_version_id == version.id, SequenceStep.kind.in_(["MESSAGE", "PHOTO", "VIDEO_NOTE"])))
        assert counts == {WELCOME_CODE: 20, PREPURCHASE_CODE: 17}
        assert session.scalar(select(func.count(ContentItem.id))) == 80
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
        final_pin = session.scalar(select(SequenceStep).where(SequenceStep.step_key == "welcome_final_pin"))
        assert final_pin.configuration["pin_after_send"] is True
        assert final_pin.configuration["buttons"][0]["url"] == "{{personal_masterclass_url}}"
        assert session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_start_masterclass_owned")).startswith("<b>Привет!</b>")
        waiting = session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_intensive_entry_continue"))
        assert waiting.startswith("<b>Спокойно!")
        assert "{{next_message_at}}" in waiting
        complete = session.scalar(select(ContentItem.body_source).where(ContentItem.code == "tpl_intensive_entry_delivered"))
        assert complete.startswith("<b>Сделайте похудение проще</b>")
        assert complete.count("{{personal_intensive_url}}") == 4
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
        assert session.scalar(select(SequenceStep.id).where(SequenceStep.sequence_version_id == latest_welcome.id, SequenceStep.step_key == "welcome_final_image"))
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
        subscription_checks = [
            step for step in checks
            if step.configuration.get("condition") == "subscription_check"
        ]
        assert subscription_checks
        assert all(step.configuration["enabled"] is True for step in subscription_checks)

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
        assert len(steps) == 11
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
        closing_review = next(step for step in steps if step.step_key == "pp_closing_review_copy")
        assert closing_review.configuration["trigger"] == "closing_review_submitted"
        assert not any(step.step_key.startswith("pp_review_week_day") for step in steps)
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


def test_start_is_idempotent_and_schedules_day1_reminder_from_run_start(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        bot = session.scalar(select(BotInstance))
        user = CrmUser(display_name="Получатель")
        session.add(user); session.flush()
        contact = Contact(bot_instance_id=bot.id, user_id=user.id, telegram_user_id="42", chat_id="42")
        session.add(contact); session.commit()
        run = start_run(session, contact.id, WELCOME_CODE)
        assert start_run(session, contact.id, WELCOME_CODE).id == run.id
        sender = FakeSender()
        advance_run(session, run, sender)
        assert sender.sent == []
        assert run.status == "active"
        assert run.current_step_key == "welcome_reminder_check_day1"
        assert run.next_action_at == run.started_at + timedelta(minutes=15)


def test_final_pin_error_does_not_stop_welcome(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        bot = session.scalar(select(BotInstance))
        user = CrmUser(display_name="Получатель")
        session.add(user); session.flush()
        contact = Contact(bot_instance_id=bot.id, user_id=user.id, telegram_user_id="pin", chat_id="pin")
        session.add(contact); session.commit()
        run = start_run(session, contact.id, WELCOME_CODE)
        run.current_step_key = "welcome_final_pin"
        advance_run(session, run, FakeSender(fail_pin=True))
        delivery = session.scalar(select(StepDelivery).where(StepDelivery.step_key == "welcome_final_pin"))
        assert delivery.status == "sent"
        assert delivery.payload_snapshot["pin_error"] == "pin is unavailable"


def test_unopened_day_reminder_is_sent_only_once_and_sets_canonical_tag(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        bot = session.scalar(select(BotInstance))
        user = CrmUser(display_name="Получатель")
        reminder_tag = CrmTag(
            id="5f56aba0-74be-49af-bec9-c2799b260411",
            code="post_small_steps",
            name="Пост - Маленькие шаги",
            category="content",
        )
        session.add_all([user, reminder_tag]); session.flush()
        contact = Contact(bot_instance_id=bot.id, user_id=user.id, telegram_user_id="sub", chat_id="sub")
        session.add(contact); session.commit()
        run = start_run(session, contact.id, WELCOME_CODE)
        sender = FakeSender(subscription=True)
        advance_run(session, run, sender)
        advance_run(session, run, sender)
        assert [item[1] for item in sender.sent] == [
            "tpl_intensive_reminder_photo",
            "tpl_intensive_day1_reminder",
        ]
        assert session.scalar(select(CrmUserTag.id).where(
            CrmUserTag.user_id == user.id,
            CrmUserTag.tag_id == reminder_tag.id,
        ))

        run.current_step_key = "welcome_reminder_check_day2"
        advance_run(session, run, sender)
        assert len(sender.sent) == 2
        assert run.current_step_key == "welcome_mid2_tag_check"


def test_opened_day_suppresses_reminder(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        bot = session.scalar(select(BotInstance))
        user = CrmUser(display_name="Получатель")
        reminder_tag = CrmTag(
            id="5f56aba0-74be-49af-bec9-c2799b260411",
            code="post_small_steps",
            name="Пост - Маленькие шаги",
            category="content",
        )
        session.add_all([user, reminder_tag]); session.flush()
        contact = Contact(bot_instance_id=bot.id, user_id=user.id, telegram_user_id="opened", chat_id="opened")
        session.add(contact)
        session.execute(text("""
            CREATE TABLE course_stage_progress (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                course_code TEXT NOT NULL,
                stage_number INTEGER NOT NULL
            )
        """))
        session.execute(
            text("INSERT INTO course_stage_progress VALUES ('p1', :user_id, 'intensive', 1)"),
            {"user_id": user.id},
        )
        session.commit()
        run = start_run(session, contact.id, WELCOME_CODE)
        run.current_step_key = "welcome_reminder_check_day1"
        sender = FakeSender(subscription=True)

        advance_run(session, run, sender)

        assert sender.sent == []
        assert run.current_step_key == "welcome_mid1_tag_check"


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
        sequence = session.scalar(select(Sequence).where(Sequence.code == WELCOME_CODE))
        version = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == sequence.id, SequenceVersion.status == "published"))
        welcome_steps = session.scalars(select(SequenceStep).where(SequenceStep.sequence_version_id == version.id)).all()
        assert not any(step.configuration.get("condition") == "has_product" for step in welcome_steps)


def test_sequence_stops_before_unapproved_message(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_intensive_day2"))
        item.editorial_status = "draft"
        bot = session.scalar(select(BotInstance))
        user = CrmUser(display_name="Получатель")
        session.add(user); session.flush()
        contact = Contact(bot_instance_id=bot.id, user_id=user.id, telegram_user_id="draft", chat_id="draft")
        session.add(contact); session.commit()
        run = start_run(session, contact.id, WELCOME_CODE)
        run.current_step_key = "welcome_day2"
        sender = FakeSender()
        advance_run(session, run, sender)

        assert run.status == "error"
        assert run.last_error == "Content is not owner-approved: tpl_intensive_day2"
        assert "tpl_intensive_day2" not in [item[1] for item in sender.sent]


def test_welcome_timing_and_subscription_observation_steps(tmp_path):
    with session_factory(tmp_path) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        sequence = session.scalar(select(Sequence).where(Sequence.code == WELCOME_CODE))
        version = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == sequence.id).order_by(SequenceVersion.version_no.desc()))
        steps = {step.step_key: step for step in session.scalars(select(SequenceStep).where(SequenceStep.sequence_version_id == version.id))}
        assert steps["welcome_reminder_delay_day1"].delay_seconds == 15 * 60
        assert steps["welcome_mid1_delay"].delay_seconds == 12 * 3600
        assert steps["welcome_day2_delay"].delay_seconds == 24 * 3600
        assert steps["welcome_day3_delay"].delay_seconds == 24 * 3600
        assert steps["welcome_day4_delay"].delay_seconds == 24 * 3600
        assert steps["welcome_final_delay"].delay_seconds == 24 * 3600
        assert steps["welcome_mid2_delay_late"].delay_seconds == 14 * 3600
        assert steps["welcome_mid3_delay_late"].delay_seconds == 14 * 3600
        stages = {step.configuration.get("stage") for step in steps.values() if step.configuration.get("condition") == "subscription_check"}
        assert {"after_day1", "after_mid1", "after_day2", "after_mid2", "after_day3", "after_mid3", "after_day4"} <= stages
        assert not [issue for issue in graph_issues(session, version) if issue["severity"] == "error"]


def test_complete_welcome_flow_resolves_all_personal_links_for_both_subscription_branches(tmp_path):
    for subscribed, suffix in ((True, "subscribed"), (False, "unsubscribed")):
        branch_path = tmp_path / suffix
        branch_path.mkdir()
        with session_factory(branch_path) as session:
            seed_defaults(
                session,
                "Fitness_Talks_bot",
                enable_subscription_checks=True,
            )
            bot = session.scalar(select(BotInstance))
            user = CrmUser(display_name=f"Получатель {suffix}")
            tags = [
                CrmTag(
                    id=tag_id,
                    code=f"content_{index}_{suffix}",
                    name=name,
                    category="content",
                )
                for index, (tag_id, name) in enumerate(
                    (
                        ("5f56aba0-74be-49af-bec9-c2799b260411", "Пост - Маленькие шаги"),
                        ("bb40957b-f598-4562-a096-7e06a4479058", "Пост - Висцеральный жир"),
                        ("e602d751-7ecf-4d75-9dac-d62c88276845", "Пост - На 1% лучше!"),
                        ("c767ab6a-45d6-41bc-808e-d0d11f0ef358", "Пост - Пирамида похудения"),
                    ),
                    1,
                )
            ]
            session.add_all([user, *tags])
            session.flush()
            contact = Contact(
                bot_instance_id=bot.id,
                user_id=user.id,
                telegram_user_id=f"flow-{suffix}",
                chat_id=f"flow-{suffix}",
            )
            session.add(contact)
            session.execute(text("""
                CREATE TABLE course_stage_progress (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    course_code TEXT NOT NULL,
                    stage_number INTEGER NOT NULL
                )
            """))
            for day in range(1, 5):
                session.execute(
                    text("INSERT INTO course_stage_progress VALUES (:id, :user_id, 'intensive', :day)"),
                    {"id": f"{suffix}-{day}", "user_id": user.id, "day": day},
                )
            session.commit()

            run = start_run(session, contact.id, WELCOME_CODE)
            sender = FakeSender(subscription=subscribed)
            for _ in range(20):
                if run.status != "active":
                    break
                advance_run(session, run, sender)

            assert run.status == "completed"
            sent_codes = [item[1] for item in sender.sent]
            assert f"tpl_intensive_mid1_{suffix}" in sent_codes
            assert f"tpl_intensive_mid2_{suffix}" in sent_codes
            assert f"tpl_intensive_mid3_{suffix}" in sent_codes
            assert "tpl_intensive_day4" in sent_codes
            assert sent_codes[-2:] == [
                "tpl_intensive_masterclass_pin",
                "tpl_intensive_masterclass_followup_image",
            ]
            assert sender.pinned
            assert all("{{" not in body for body in sender.bodies)
            assert all("{{" not in str(item[2]) for item in sender.sent)
            assert any("https://t.me/Fitness_Talks/734" in str(item[2]) for item in sender.sent) == subscribed
            if not subscribed:
                assert any("https://t.me/Fitness_Talks/328" in body for body in sender.bodies)
            assert not any("/p/" in body for body in sender.bodies)
            assert not any("/p/" in str(item[2]) for item in sender.sent)
