import json
from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.database import Base, make_engine
from app.models import ContentItem, Contact, CrmUser, SequenceRun, SequenceStep, TrackingEvent, BotInstance
from app.seed import seed_defaults
from app.onepage_campaign import (PrepareIn, LiveIn, TestIn as PreviewIn, prepare, set_live,
    build_graph, slot_hour, send_test, SKIP, ENTRY_CODES, family_received)
from app.engine import advance_run, start_run
from app.graph_authoring import parse_source


class Sender:
    def __init__(self, subscribed=False):
        self.sent=[]; self.subscribed=subscribed
    def subscription_status(self, uid):
        return self.subscribed
    def send_content(self, chat, content, config):
        self.sent.append((chat,content.code,content.body_source,config))
        return str(len(self.sent))


@pytest.fixture
def campaign(tmp_path):
    engine=make_engine(f"sqlite:///{tmp_path/'campaign.db'}")
    Base.metadata.create_all(engine)
    with Session(engine,autoflush=False) as session:
        seed_defaults(session,"Fitness_Talks_bot")
        for n in range(1,61):
            for suffix in ("tg_full","tg_channel","max_full"):
                session.add(ContentItem(code=f"tpl_nurture_{n:02d}_{suffix}",title="Пост",body_source="",source_markdown="",
                    purpose="Цель",writer_brief="ТЗ",origin_system="obsidian_nurture_60"))
        user=CrmUser(display_name="Владелец",status="active",data_origin="native")
        session.add(user); session.flush()
        bot=session.scalar(select(BotInstance).where(BotInstance.code=="test"))
        contact=Contact(bot_instance_id=bot.id,user_id=user.id,telegram_user_id="446056103",chat_id="446056103")
        session.add(contact); session.commit()
        prepare(session,PrepareIn(confirm=True))
        for group in ENTRY_CODES.values():
            for name in ("navigation","first_video","repeat_video","owned"):
                item=session.scalar(select(ContentItem).where(ContentItem.code==group[name]))
                if (item.body_source or "").strip()==SKIP:
                    item.body_source="Готовый вход"; item.source_markdown="Готовый вход"
        session.commit()
        yield session,contact
    engine.dispose()


def approve(session,code,body="Текст",family=None):
    item=session.scalar(select(ContentItem).where(ContentItem.code==code))
    item.body_source=body; item.source_markdown=body
    item.status="published"; item.editorial_status="approved"
    if family: item.labels=["campaign_family:"+family]
    session.commit()


def test_graph_contains_every_variant_and_preserves_exact_slot_times():
    assert [slot_hour(n) for n in range(1,11)]==[24,36,48,60,72,84,96,108,120,144]
    for code in ("welcome_intensive","prepurchase_nurture"):
        parsed=parse_source(json.dumps(build_graph(code)),code)
        assert parsed.steps and parsed.edges
    doc=build_graph("prepurchase_nurture")
    assert len([s for s in doc["steps"] if s["kind"]=="DELAY"])==60
    assert doc["steps"][-1]["kind"]=="STOP"


def test_prepare_is_inactive_idempotent_and_preserves_originals(campaign):
    session,contact=campaign
    approve(session,ENTRY_CODES["tg"]["first_video"],"Правка владельца")
    assert prepare(session,PrepareIn(confirm=True))["status"]=="already_prepared"
    assert session.scalar(select(ContentItem.body_source).where(ContentItem.code==ENTRY_CODES["tg"]["first_video"]))=="Правка владельца"
    assert session.scalar(select(func.count()).select_from(SequenceRun))==0


def test_skip_does_not_collapse_next_deadline(campaign):
    session,contact=campaign
    set_live(session,LiveIn(enabled=True,confirm=True))
    run=start_run(session,contact.id,"prepurchase_nurture")
    run.started_at=datetime.now(UTC)
    sender=Sender()
    advance_run(session,run,sender)
    assert run.current_step_key=="post_01" and sender.sent==[]
    advance_run(session,run,sender)
    assert run.current_step_key=="post_02"
    assert (run.next_action_at.replace(tzinfo=UTC)-run.started_at.replace(tzinfo=UTC)).total_seconds()==36*3600
    assert sender.sent==[]


def test_successful_family_not_repeated_at_another_slot(campaign):
    session,contact=campaign
    for n in (1,2):
        approve(session,f"tpl_nurture_{n:02d}_tg_full",family="same_material")
    set_live(session,LiveIn(enabled=True,confirm=True))
    run=start_run(session,contact.id,"prepurchase_nurture")
    sender=Sender()
    advance_run(session,run,sender); advance_run(session,run,sender); advance_run(session,run,sender)
    assert len(sender.sent)==1 and family_received(session,contact,"same_material")


def test_early_percent_and_6h_never_duplicate(campaign):
    session,contact=campaign
    approve(session,ENTRY_CODES["tg"]["percent_unread"])
    set_live(session,LiveIn(enabled=True,confirm=True))
    run=start_run(session,contact.id,"welcome_intensive")
    sender=Sender()
    advance_run(session,run,sender); advance_run(session,run,sender); advance_run(session,run,sender)
    assert [row[1] for row in sender.sent]==[ENTRY_CODES["tg"]["percent_unread"]]
    assert run.current_step_key=="second_belly"


def test_owner_preview_has_no_run_or_family_receipts(campaign):
    session,contact=campaign
    approve(session,ENTRY_CODES["tg"]["owned"],"Памятка")
    approve(session,ENTRY_CODES["tg"]["percent_unread"])
    sender=Sender()
    body=PreviewIn(test_id="a"*32,confirm=True)
    result=send_test(session,body,sender)
    assert result["total"]>=5 and len(sender.sent)==5
    assert all(row[0]=="446056103" for row in sender.sent)
    assert session.scalar(select(func.count()).select_from(SequenceRun))==0
    assert not family_received(session,contact,"one_percent")
    send_test(session,body,sender)
    assert len(sender.sent)==5


def test_preview_never_falls_back_to_another_contact(campaign):
    session,contact=campaign
    contact.telegram_user_id="123"; session.commit()
    sender=Sender()
    with pytest.raises(Exception,match="Владелец"):
        send_test(session,PreviewIn(test_id="b"*32,confirm=True),sender)
    assert sender.sent==[]


def test_pausing_prevents_actual_delivery(campaign):
    session,contact=campaign
    set_live(session,LiveIn(enabled=True,confirm=True))
    run=start_run(session,contact.id,"prepurchase_nurture")
    set_live(session,LiveIn(enabled=False,confirm=True))
    sender=Sender(); advance_run(session,run,sender)
    assert run.status=="paused" and sender.sent==[]


@pytest.mark.parametrize("percent,subscribed,expected", [(74,False,"percent_unread"),(75,False,"percent_read"),(100,True,None)])
def test_opened_article_6h_uses_75_percent_and_subscription(campaign,monkeypatch,percent,subscribed,expected):
    session,contact=campaign
    monkeypatch.setattr("app.onepage_campaign.reading_facts",lambda *_:{"opened":True,"read_percent":percent,"homepage_opened":False})
    for name in ("percent_unread","percent_read"):
        approve(session,ENTRY_CODES["tg"][name])
    set_live(session,LiveIn(enabled=True,confirm=True))
    run=start_run(session,contact.id,"welcome_intensive")
    sender=Sender(subscribed)
    advance_run(session,run,sender); advance_run(session,run,sender); advance_run(session,run,sender)
    assert [row[1] for row in sender.sent]==([ENTRY_CODES["tg"][expected]] if expected else [])


@pytest.mark.parametrize("subscribed,suffix",[(True,"tg_full"),(False,"tg_channel"),(None,"tg_full")])
def test_fifth_day_selects_subscription_variant(campaign,subscribed,suffix):
    session,contact=campaign
    for variant in ("tg_full","tg_channel"):
        approve(session,"tpl_nurture_07_"+variant)
    set_live(session,LiveIn(enabled=True,confirm=True))
    run=start_run(session,contact.id,"prepurchase_nurture")
    run.current_step_key="post_07"
    sender=Sender(subscribed)
    advance_run(session,run,sender)
    assert [row[1] for row in sender.sent]==["tpl_nurture_07_"+suffix]


def test_max_receives_full_without_subscription_check(campaign):
    session,contact=campaign
    bot=session.scalar(select(BotInstance).where(BotInstance.code=="max"))
    if not bot:
        bot=BotInstance(code="max",username="max",display_name="MAX",token_env_name="MAX_BOT_TOKEN"); session.add(bot); session.flush()
    contact.bot_instance_id=bot.id; session.commit()
    approve(session,"tpl_nurture_07_max_full")
    set_live(session,LiveIn(enabled=True,confirm=True))
    run=start_run(session,contact.id,"prepurchase_nurture"); run.current_step_key="post_07"
    class MaxSender(Sender):
        def subscription_status(self,uid):
            raise AssertionError("MAX не проверяет Telegram-подписку")
    sender=MaxSender(); advance_run(session,run,sender)
    assert [row[1] for row in sender.sent]==["tpl_nurture_07_max_full"]


def test_customer_guard_stops_before_message(campaign,monkeypatch):
    session,contact=campaign
    approve(session,"tpl_nurture_01_tg_full")
    set_live(session,LiveIn(enabled=True,confirm=True))
    run=start_run(session,contact.id,"prepurchase_nurture"); run.current_step_key="post_01"
    monkeypatch.setattr("app.temporary_entry.entry_decision",lambda *_:"owned")
    sender=Sender(); advance_run(session,run,sender)
    assert run.status=="stopped" and sender.sent==[]


def test_preview_all_batches_include_both_fifth_day_variants(campaign):
    session,contact=campaign
    for group in ENTRY_CODES.values():
        for code in group.values(): approve(session,code)
    for n in range(1,9):
        for suffix in ("tg_full","tg_channel"): approve(session,f"tpl_nurture_{n:02d}_{suffix}")
    sender=Sender(); offset=0
    while True:
        result=send_test(session,PreviewIn(test_id="c"*32,offset=offset,confirm=True),sender)
        offset=result["next_offset"]
        if offset>=result["total"]: break
    codes=[row[1] for row in sender.sent]
    assert len(codes)==17
    assert codes[:7]==list(ENTRY_CODES["tg"].values())
    assert "tpl_nurture_07_tg_channel" in codes and "tpl_nurture_08_tg_channel" in codes
    assert session.scalar(select(func.count()).select_from(SequenceRun))==0


def test_new_family_in_passed_slot_is_queued_without_start_or_deadline_change(campaign):
    from app.onepage_campaign import queue_added_family
    session,contact=campaign
    set_live(session,LiveIn(enabled=True,confirm=True))
    run=start_run(session,contact.id,"prepurchase_nurture")
    run.current_step_key="post_09_delay"; run.next_action_at=datetime.now(UTC)+timedelta(hours=24)
    original_time=run.next_action_at
    approve(session,"tpl_nurture_01_tg_full",family="added_material")
    item=session.scalar(select(ContentItem).where(ContentItem.code=="tpl_nurture_01_tg_full"))
    queue_added_family(session,item); session.commit()
    assert run.context["campaign_pending"][0]["family"]=="added_material"
    sender=Sender(); advance_run(session,run,sender)
    assert [row[1] for row in sender.sent]==[item.code]
    assert run.current_step_key=="post_09_delay" and run.next_action_at.replace(tzinfo=UTC)==original_time.replace(tzinfo=UTC)
    queue_added_family(session,item)
    assert run.context["campaign_pending"]==[]


def test_stale_scheduler_context_does_not_erase_published_pending(campaign):
    session,contact=campaign
    set_live(session,LiveIn(enabled=True,confirm=True))
    run=start_run(session,contact.id,"prepurchase_nurture"); run.current_step_key="post_09_delay"
    session.commit(); _=run.context
    original_time=run.next_action_at
    with Session(session.bind) as other:
        competing=other.get(SequenceRun,run.id)
        competing.context={**competing.context,"campaign_pending":[{"family":"late_family","step_key":"post_01"}]}
        other.commit()
    sender=Sender(); advance_run(session,run,sender)
    assert run.current_step_key=="post_09_delay"
    assert run.context["campaign_pending"]==[]
    # The pending gate was processed, not lost to a stale ordinary delay update.
    assert run.next_action_at==original_time


def test_engine_persists_partial_media_receipt_on_retry(campaign):
    from app.models import StepDelivery
    from app.telegram import TelegramError
    session,contact=campaign
    approve(session,"tpl_nurture_01_tg_full")
    set_live(session,LiveIn(enabled=True,confirm=True))
    run=start_run(session,contact.id,"prepurchase_nurture"); run.current_step_key="post_01"
    class PartialSender(Sender):
        def send_content(self,chat,content,config):
            if not config.get("media_message_id"):
                config["media_message_id"]="photo-already-sent"
                raise TelegramError("HTTP 500 temporary")
            assert config["media_message_id"]=="photo-already-sent"
            return super().send_content(chat,content,config)
    sender=PartialSender(); advance_run(session,run,sender)
    receipt=session.scalar(select(StepDelivery).where(StepDelivery.run_id==run.id))
    assert receipt.payload_snapshot["media_message_id"]=="photo-already-sent"
    advance_run(session,run,sender)
    assert len(sender.sent)==1 and receipt.status=="sent"
