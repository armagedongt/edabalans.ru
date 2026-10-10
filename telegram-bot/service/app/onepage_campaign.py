"""The agreed one-page funnel, using the existing versioned sequence engine."""
from __future__ import annotations

from datetime import UTC, datetime
from sqlalchemy import select, text
from app.models import ContentItem, Contact, SequenceStep, SequenceVersion, TrackingEvent
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
import json
import re

CAMPAIGN = "onepage_20261010"
SKIP = "[[SKIP]]"
ENTRY_CODES = {
    platform: {name: f"tpl_onepage_{name}_{platform}" for name in
               ("navigation", "first_video", "repeat_video", "owned", "percent_unread", "percent_read", "second_belly")}
    for platform in ("tg", "max")
}


def is_campaign_content(code):
    return code in {code for group in ENTRY_CODES.values() for code in group.values()} or bool(
        re.fullmatch(r"tpl_nurture_(0[1-9]|[1-5][0-9]|60)_(tg_full|tg_channel|max_full)", code))


def slot_hour(number):
    if not 1 <= number <= 60:
        raise ValueError("Номер поста должен быть от 1 до 60")
    return 12 + number * 12 if number <= 8 else 120 + (number - 9) * 24


def family_received(session, contact, family):
    return bool(contact.user_id and session.scalar(select(TrackingEvent.id).where(
        TrackingEvent.deduplication_key == f"{CAMPAIGN}:family:{contact.user_id}:{family}")))


def record_family(session, contact, family, content_code, message_id):
    if not contact.user_id or family_received(session, contact, family):
        return
    session.add(TrackingEvent(contact_id=contact.id, user_id=contact.user_id,
        telegram_user_id=contact.telegram_user_id, event_type="campaign_family_sent",
        deduplication_key=f"{CAMPAIGN}:family:{contact.user_id}:{family}",
        metadata_json={"campaign": CAMPAIGN, "family": family, "content_code": content_code,
                       "message_id": str(message_id)}))
    session.flush()


def reading_facts(session, contact):
    if not contact.user_id or session.bind.dialect.name != "postgresql":
        return {"opened": False, "read_percent": 0, "homepage_opened": False}
    # Facts remain owned by the website. Do not substitute button clicks for reading.
    row = session.execute(text("""
        SELECT
          EXISTS(SELECT 1 FROM attribution_events WHERE user_id = :uid
                 AND event_type = 'intensive_personal_link_open') AS opened,
          COALESCE((SELECT MAX((details->>'viewed_percent')::int) FROM course_events
                    WHERE user_id = :uid AND course_code = 'intensive'
                    AND event_type IN ('intensive_onepage_progress','intensive_onepage_heading',
                                       'intensive_onepage_reading_start')),0) AS read_percent,
          EXISTS(SELECT 1 FROM attribution_events WHERE user_id = :uid
                 AND event_type = 'personal_masterclass_link_open') AS homepage_opened
    """), {"uid": contact.user_id}).mappings().one()
    return dict(row)


def before_message(session, run, contact, step, sender):
    from app.engine import _contact_platform, _record_subscription_check
    subscribed = None
    if _contact_platform(session, contact) == "telegram":
        try:
            subscribed = sender.subscription_status(contact.telegram_user_id)
        except Exception:
            subscribed = None
    _record_subscription_check(session, run, contact, step, subscribed)
    facts = reading_facts(session, contact)
    session.add(TrackingEvent(contact_id=contact.id, user_id=contact.user_id,
        telegram_user_id=contact.telegram_user_id, event_type="campaign_before_message",
        metadata_json={"campaign": CAMPAIGN, "run_id": run.id, "step_key": step.step_key,
                       "previous_family": run.context.get("last_family"),
                       "subscribed": subscribed, **facts}))
    run.context = {**run.context, "campaign_subscribed": subscribed, "campaign_reading": facts}
    return facts, subscribed


def before_direct(session, contact, code, sender):
    from types import SimpleNamespace
    latest=session.scalar(select(TrackingEvent).where(TrackingEvent.user_id==contact.user_id,
        TrackingEvent.event_type.in_(["campaign_direct_sent","campaign_family_sent"])).order_by(TrackingEvent.occurred_at.desc(),TrackingEvent.id.desc()))
    context={"last_family":latest.metadata_json.get("family") if latest else None}
    before_message(session,SimpleNamespace(id=None,context=context),contact,SimpleNamespace(step_key=code,configuration={}),sender)


def record_direct(session, contact, family, message_id):
    session.add(TrackingEvent(contact_id=contact.id,user_id=contact.user_id,telegram_user_id=contact.telegram_user_id,
        event_type="campaign_direct_sent",metadata_json={"campaign":CAMPAIGN,"family":family,"message_id":str(message_id)}))


def campaign_version(session, code):
    from app.engine import published_version
    version = published_version(session, code)
    if not version:
        return None
    first = session.scalar(select(SequenceStep).where(
        SequenceStep.sequence_version_id == version.id).order_by(SequenceStep.position))
    return version if first and first.configuration.get("campaign") == CAMPAIGN else None


def live(session):
    version = campaign_version(session, "welcome_intensive")
    if not version:
        return False
    first = session.scalar(select(SequenceStep).where(
        SequenceStep.sequence_version_id == version.id).order_by(SequenceStep.position))
    return first.configuration.get("campaign_live") is True


def build_graph(code, families=None):
    """Explicit edges for every platform/subscription/reading branch; no messages sent."""
    families = families or {}
    steps, edges = [], []
    def node(key, kind, label, content=None, delay=None, **config):
        steps.append(dict(step_key=key, position=len(steps)+1, kind=kind, label=label,
                          content_code=content, delay_seconds=delay, next_step_key=None,
                          configuration={"campaign": CAMPAIGN, **config}, enabled=True))
        return key
    def edge(a, b, branch="default", sequence=None):
        edges.append(dict(from_step_key=a, to_step_key=b, target_sequence_code=sequence,
                          branch_key=branch, label=branch, condition={}, priority=0, enabled=True))
    def variants(prefix, full, max_full, after, channel=None, family=None):
        gate = node(prefix, "CONDITION", "Telegram или MAX", condition="campaign_telegram")
        tg = node(prefix+"_tg", "MESSAGE", "Telegram — полный", full, family_id=family,
                  before_message_snapshot=True, link_preview=False, media_separate=True)
        mx = node(prefix+"_max", "MESSAGE", "MAX — полный", max_full, family_id=family,
                  before_message_snapshot=True, link_preview=False)
        edge(gate, mx, "false")
        if channel:
            check = node(prefix+"_subscription", "CONDITION", "Подписан на канал?", condition="subscription_check", enabled=True)
            teaser = node(prefix+"_channel", "MESSAGE", "Telegram — ссылка в канал", channel,
                          family_id=family, before_message_snapshot=True, link_preview=False, media_separate=True)
            edge(gate, check, "true"); edge(check, tg, "true"); edge(check, teaser, "false"); edge(teaser, after)
        else:
            edge(gate, tg, "true")
        edge(tg, after); edge(mx, after)
        return gate
    if code == "welcome_intensive":
        node("delay_5m", "DELAY", "+5 минут", delay=300, anchor_step="run_started_at", campaign_live=False)
        node("check_open", "CONDITION", "Статья ещё не открыта?", condition="campaign_unopened")
        variants("percent_early", ENTRY_CODES["tg"]["percent_unread"], ENTRY_CODES["max"]["percent_unread"], "delay_6h", family="one_percent")
        node("delay_6h", "DELAY", "+6 часов", delay=21600, anchor_step="run_started_at")
        node("check_reminder", "CONDITION", "Нет подписки и ещё не отправляли 1%?", condition="campaign_needs_percent")
        node("check_read", "CONDITION", "Прочитано хотя бы 75%?", condition="campaign_read")
        variants("percent_unread", ENTRY_CODES["tg"]["percent_unread"], ENTRY_CODES["max"]["percent_unread"], "delay_12h", family="one_percent")
        variants("percent_read", ENTRY_CODES["tg"]["percent_read"], ENTRY_CODES["max"]["percent_read"], "delay_12h", family="one_percent")
        node("delay_12h", "DELAY", "+12 часов", delay=43200, anchor_step="run_started_at")
        variants("second_belly", ENTRY_CODES["tg"]["second_belly"], ENTRY_CODES["max"]["second_belly"], "handoff", family="second_belly")
        node("handoff", "GOTO", "Перейти к 60 постам", carry_campaign_start=True)
        edge("delay_5m", "check_open"); edge("check_open", "percent_early", "true"); edge("check_open", "delay_6h", "false")
        edge("delay_6h", "check_reminder"); edge("check_reminder", "check_read", "true"); edge("check_reminder", "delay_12h", "false")
        edge("check_read", "percent_read", "true"); edge("check_read", "percent_unread", "false")
        edge("delay_12h", "second_belly"); edge("handoff", None, sequence="prepurchase_nurture")
    elif code == "prepurchase_nurture":
        for n in range(1, 61):
            prefix = f"post_{n:02d}"
            node(prefix+"_delay", "DELAY", f"Пост {n:02d}: +{slot_hour(n)} часов", delay=slot_hour(n)*3600, anchor_step="run_started_at")
            variants(prefix, f"tpl_nurture_{n:02d}_tg_full", f"tpl_nurture_{n:02d}_max_full",
                     f"post_{n+1:02d}_delay" if n<60 else "stop",
                     f"tpl_nurture_{n:02d}_tg_channel" if slot_hour(n)>=96 else None,
                     family=families.get(str(n), f"slot_{n:02d}"))
            edge(prefix+"_delay", prefix)
        node("stop", "STOP", "60 позиций закончились")
    else:
        raise ValueError("Неизвестная цепочка")
    return dict(schema_version=1, sequence=dict(code=code, name="Одностраничная рассылка", description=CAMPAIGN, status="published"), steps=steps, edges=edges)


class PrepareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: dict[str, str] = Field(default_factory=dict, max_length=194)
    families: dict[str, str] = Field(default_factory=dict, max_length=60)
    confirm: Literal[True]


class TestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["tg", "max"] = "tg"
    offset: int = Field(default=0, ge=0, le=60)
    count: int = Field(default=5, ge=1, le=5)
    test_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    confirm: Literal[True]


class LiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    confirm: Literal[True]


def prepare(session, body):
    from app.graph_authoring import GraphDraftIn, GraphPublishIn, load_source, publish_draft, save_draft
    from app.content_formatting import content_is_runtime_ready
    for number, family in body.families.items():
        if not number.isdigit() or not 1 <= int(number) <= 60 or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", family):
            raise HTTPException(422, "Некорректное семейство")
    for target, donor in body.sources.items():
        if not is_campaign_content(target) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", donor):
            raise HTTPException(422, "Некорректный источник")
        if not session.scalar(select(ContentItem.id).where(ContentItem.code == donor)):
            raise HTTPException(422, "Источник не найден: " + donor)
    if live(session):
        raise HTTPException(409, "Сначала остановите новые входы")
    existing_graphs = {code: load_source(session, code) for code in ("welcome_intensive", "prepurchase_nurture")}
    # Preparing twice must not replace current graphs or owner edits.
    if all(campaign_version(session, code) for code in existing_graphs):
        return {"ok": True, "status": "already_prepared", "live": False}
    for item in session.scalars(select(ContentItem).where(ContentItem.origin_system=="obsidian_nurture_60")):
        if not is_campaign_content(item.code):
            continue
        number = int(item.code.split("_")[2])
        if not any(label.startswith("campaign_family:") for label in (item.labels or [])):
            item.labels = list(item.labels or []) + ["campaign_family:"+body.families.get(str(number),f"slot_{number:02d}")]
            item.content_version += 1
        if not (item.body_source or "").strip() and not (item.source_markdown or "").strip():
            item.source_markdown=SKIP; item.body_source=SKIP
            item.editorial_status="approved"; item.status="published"
            item.content_version += 1
    for platform, group in ENTRY_CODES.items():
        for name, code in group.items():
            if session.scalar(select(ContentItem.id).where(ContentItem.code == code)):
                continue
            donor_code = body.sources.get(code) or {
                "navigation": "tpl_onepage_entry_navigation", "first_video": "tpl_temporary_intensive_entry",
                "repeat_video": "tpl_temporary_intensive_entry", "owned": "tpl_start_masterclass_owned",
            }.get(name)
            donor = session.scalar(select(ContentItem).where(ContentItem.code == donor_code)) if donor_code else None
            html = donor.body_source if donor and content_is_runtime_ready(donor) else SKIP
            if name == "repeat_video" and donor:
                offer = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_onepage_entry_repeat_offer"))
                if not offer or not content_is_runtime_ready(offer):
                    raise HTTPException(409, "Приписка повторного входа не готова")
                html += "\n\n" + offer.body_source
            session.add(ContentItem(code=code, title=f"{platform.upper()} — {name}", body_source=html,
                source_format="telegram_html", editorial_status="approved", status="published",
                purpose="Отдельный оригинал согласованной одностраничной рассылки.",
                writer_brief="Сохранять авторский текст; редактировать только по поручению владельца.",
                media_kind=donor.media_kind if donor else None, media_path=donor.media_path if donor else None,
                telegram_file_id=donor.telegram_file_id if donor and platform=="tg" else None))
            session.flush()
            created = session.scalar(select(ContentItem).where(ContentItem.code==code))
            created.origin_system = "obsidian_onepage_campaign"
    session.commit()
    for code, original in existing_graphs.items():
        if campaign_version(session, code):
            continue
        doc = build_graph(code, body.families)
        def revision(value):
            return {key:value[key] for key in ("version", "sha256")} if value else None
        draft = save_draft(session, code, GraphDraftIn(source=json.dumps(doc, ensure_ascii=False),
             expected_published=revision(original["published"]), expected_draft=revision(original["draft"])))
        publish_draft(session, code, GraphPublishIn(expected_published=revision(original["published"]),
             expected_draft=revision(draft["draft"])))
    return {"ok": True, "status": "prepared", "live": False}


def test_messages(session, platform):
    group = ENTRY_CODES[platform]
    result = [(group[name], {"link_preview": False, "media_separate": True,
              "buttons": ([{"text": "Читать прямо сейчас", "url": "{{personal_intensive_url}}"}] if name=="first_video" else
                          [{"text": "Перейти в канал", "url": "https://t.me/Fitness_Talks"}] if name=="navigation" else [])})
              for name in ("navigation", "first_video", "repeat_video", "owned", "percent_unread", "percent_read", "second_belly")]
    for n in range(1, 9):
        suffixes = ("max_full",) if platform=="max" else (("tg_full", "tg_channel") if slot_hour(n)>=96 else ("tg_full",))
        result.extend((f"tpl_nurture_{n:02d}_{suffix}", {"link_preview":False, "media_separate":True}) for suffix in suffixes)
    filled = []
    for code, config in result:
        item = session.scalar(select(ContentItem).where(ContentItem.code == code))
        if not item:
            raise HTTPException(409, "Не подготовлен оригинал: " + code)
        if (item.source_markdown or item.body_source or "").strip() != SKIP:
            filled.append((item, config))
    return filled


def send_test(session, body, sender):
    from app.engine import personalized_delivery
    from app.models import BotInstance
    from app.content_formatting import content_is_runtime_ready
    # Fixed personal owner, never a caller-selected subscriber/chat.
    contact = session.scalar(select(Contact).join(BotInstance).where(
        Contact.telegram_user_id=="446056103", BotInstance.code=="test"))
    if not contact or not contact.user_id:
        raise HTTPException(409, "Владелец должен сначала открыть основной бот")
    messages = test_messages(session, body.platform)
    # Validate the whole preview before delivering its first batch.
    if any(not content_is_runtime_ready(item) for item, _ in messages):
        raise HTTPException(409, "Сначала опубликуйте готовые оригиналы")
    sent = []
    for offset, (item, config) in enumerate(messages[body.offset:body.offset+body.count], body.offset):
        key = f"campaign_test:{body.test_id}:{body.platform}:{offset}"
        existing = session.scalar(select(TrackingEvent).where(TrackingEvent.deduplication_key==key))
        if existing:
            if existing.metadata_json.get("status") != "sent":
                raise HTTPException(409, "Неопределённый результат теста; проверьте сообщения перед новым запуском")
            sent.append(item.code); continue
        rendered, config = personalized_delivery(session, contact, item, config)
        event = TrackingEvent(contact_id=contact.id, user_id=contact.user_id, telegram_user_id=contact.telegram_user_id,
             event_type="campaign_owner_test", deduplication_key=key,
             metadata_json={"status":"pending", "content_code":item.code})
        session.add(event); session.commit()
        message_id = sender.send_content(contact.chat_id, rendered, config)
        event.metadata_json = {**event.metadata_json, "status":"sent", "message_id":str(message_id)}
        session.commit(); sent.append(item.code)
    return {"ok":True, "sent":sent, "total":len(messages), "next_offset":min(len(messages),body.offset+body.count)}


def set_live(session, body):
    version = campaign_version(session, "welcome_intensive")
    if not version or not campaign_version(session, "prepurchase_nurture"):
        raise HTTPException(409, "Сначала подготовьте оба графа")
    if body.enabled:
        from app.content_formatting import content_is_runtime_ready
        for group in ENTRY_CODES.values():
            for name in ("navigation","first_video","repeat_video","owned"):
                item=session.scalar(select(ContentItem).where(ContentItem.code==group[name]))
                if not item or not content_is_runtime_ready(item) or (item.source_markdown or item.body_source or "").strip()==SKIP:
                    raise HTTPException(409,"Сначала опубликуйте обязательное входное сообщение: "+group[name])
    first = session.scalar(select(SequenceStep).where(SequenceStep.sequence_version_id==version.id).order_by(SequenceStep.position).with_for_update())
    first.configuration = {**first.configuration, "campaign_live": body.enabled}
    session.commit()
    return {"ok": True, "live": body.enabled, "existing_pool_started": False}


def queue_added_family(session, item):
    """Catch up passed slots on existing active campaign runs, without starting anyone."""
    from app.models import SequenceRun,Sequence
    from app.engine import _contact_platform
    match=re.fullmatch(r"tpl_nurture_(\d{2})_(tg_full|tg_channel|max_full)",item.code)
    if not match or (item.source_markdown or item.body_source or "").strip()==SKIP:
        return
    family=next((label.split(":",1)[1] for label in item.labels or [] if label.startswith("campaign_family:")),None)
    if not family:
        return
    prefix="post_"+match[1]
    runs=session.scalars(select(SequenceRun).join(SequenceVersion,SequenceVersion.id==SequenceRun.sequence_version_id)
        .join(Sequence,Sequence.id==SequenceVersion.sequence_id).where(SequenceRun.status=="active",Sequence.code=="prepurchase_nurture").with_for_update(of=SequenceRun)).all()
    for run in runs:
        first=session.scalar(select(SequenceStep).where(SequenceStep.sequence_version_id==run.sequence_version_id).order_by(SequenceStep.position))
        if not first or first.configuration.get("campaign")!=CAMPAIGN:
            continue
        current=session.scalar(select(SequenceStep).where(SequenceStep.sequence_version_id==run.sequence_version_id,SequenceStep.step_key==run.current_step_key))
        gate=session.scalar(select(SequenceStep).where(SequenceStep.sequence_version_id==run.sequence_version_id,SequenceStep.step_key==prefix))
        if not gate or not current or current.position<=gate.position:
            continue
        contact=session.get(Contact,run.contact_id)
        if (_contact_platform(session,contact)=="max") != (match[2]=="max_full"):
            continue
        if family_received(session,contact,family):
            continue
        pending=list(run.context.get("campaign_pending",[]))
        if not any(entry["family"]==family for entry in pending):
            pending.append({"family":family,"step_key":prefix})
            run.context={**run.context,"campaign_pending":pending}
