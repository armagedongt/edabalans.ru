from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session

import app.main as main
from app.config import get_settings
from app.database import Base, make_engine
from app.engine import advance_run, start_run
from app.max import process_max_update
from app.models import Contact, CrmTag, CrmUserTag, UserVariable, UpdateReceipt, SequenceRun, TrackingEvent
from app.seed import seed_defaults, WELCOME_CODE
from app.temporary_entry import CONTENT_CODE, POOL_CODE, pause_marketing


class Sender:
    def __init__(self):
        self.sent = []
        self.answers = []
        self.fail = False

    def send_content(self, chat_id, content, configuration):
        self.sent.append((chat_id, content, configuration))
        if self.fail:
            raise RuntimeError("Response lost")
        return str(len(self.sent))

    def answer_callback(self, callback_id, *args, **kwargs):
        self.answers.append(callback_id)

    def reset_chat_menu_button(self, chat_id):
        pass


@pytest.fixture
def setup(tmp_path, monkeypatch):
    db = make_engine(f"sqlite:///{tmp_path / 'temporary.sqlite'}")
    Base.metadata.create_all(db)
    session = Session(db)
    seed_defaults(session, "TetrisgfgfgfBot")
    session.commit()
    monkeypatch.setattr(get_settings(), "temporary_intensive_entry_enabled", True)
    monkeypatch.setattr(main.settings, "telegram_maintenance_mode", False)
    sender = Sender()
    monkeypatch.setattr(main, "client", lambda: sender)
    yield session, sender
    session.close()
    db.dispose()


def tg(n, text="/start"):
    return {"update_id": n, "message": {"message_id": n, "from": {"id": 4101}, "chat": {"id": 4101, "type": "private"}, "text": text}}


def max_event(n, kind="bot_started"):
    event = {"update_type": kind, "timestamp": n, "user": {"user_id": 5101, "name": "Тест"}}
    if kind == "message_created":
        event.pop("user")
        event["message"] = {"sender": {"user_id": 5101}, "recipient": {"chat_type": "dialog"}, "body": {"mid": f"m{n}", "text": "Привет"}}
    if kind == "message_callback":
        event["callback"] = {"callback_id": f"cb{n}", "user": event.pop("user"), "payload": "start_intensive"}
    return event


def run_max(session, sender, event):
    return process_max_update(session, event, bot_username="test_bot", intensive_public_url="https://edabalans.ru/intensive", sender=sender)


def assert_invitation(session, sender):
    _, content, config = sender.sent[-1]
    assert content.code == CONTENT_CODE
    url = config["buttons"][0]["url"]
    assert url in content.body_source and "{{" not in content.body_source
    assert urlparse(url).path == "/intensive"
    assert parse_qs(urlparse(url).query).get("i")
    assert config["link_preview"] is False
    assert session.scalar(select(func.count()).select_from(SequenceRun)) == 0


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_start_repeat_message_callback_and_duplicate(setup, platform):
    session, sender = setup
    if platform == "telegram":
        events = [tg(1), tg(2), tg(3, "Привет"), {"update_id": 4, "callback_query": {"id": "cb4", "from": {"id": 4101}, "message": {"chat": {"id": 4101}}, "data": "start_intensive"}}]
        invoke = lambda e: main.process_update(e, session)
    else:
        events = [max_event(1), max_event(2), max_event(3, "message_created"), max_event(4, "message_callback")]
        invoke = lambda e: run_max(session, sender, e)
    for e in events:
        assert invoke(e)["temporary_entry"]
        assert_invitation(session, sender)
    assert len(sender.sent) == 4
    assert invoke(events[-1])["duplicate"]
    assert len(sender.sent) == 4
    tag = session.scalar(select(CrmTag).where(CrmTag.code == POOL_CODE))
    assert session.scalar(select(func.count()).select_from(CrmUserTag).where(CrmUserTag.tag_id == tag.id)) == 1
    assert sender.answers == ["cb4"]


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("exclusion", ["blocked", "stopped", "stop_tag", "buyer"])
def test_exclusions_preserved(setup, platform, exclusion):
    session, sender = setup
    invoke = (lambda n: main.process_update(tg(n), session)) if platform == "telegram" else (lambda n: run_max(session, sender, max_event(n)))
    invoke(1)
    contact = session.scalar(select(Contact))
    pool = session.scalar(select(CrmTag).where(CrmTag.code == POOL_CODE))
    for assignment in session.scalars(select(CrmUserTag).where(CrmUserTag.tag_id == pool.id)):
        session.delete(assignment)
    if exclusion in {"blocked", "stopped"}:
        contact.status = exclusion
    elif exclusion == "stop_tag":
        stop = CrmTag(code="test_stop", name="Стоп - До покупки мастер-класса", category="manual", status="active")
        session.add(stop); session.flush()
        session.add(CrmUserTag(user_id=contact.user_id, tag_id=stop.id, source="manual"))
    else:
        session.add(UserVariable(contact_id=contact.id, key="has_product:masterclass", value={"value": True}))
    session.commit()
    sender.sent.clear()
    invoke(2)
    assert all(content.code != CONTENT_CODE for _, content, _ in sender.sent)
    assert session.scalar(select(func.count()).select_from(CrmUserTag).where(CrmUserTag.tag_id == pool.id)) == 0
    if exclusion in {"blocked", "stopped"}:
        assert contact.status == exclusion
        assert not sender.sent
    elif exclusion == "buyer":
        assert sender.sent
    else:
        assert not sender.sent


def test_lost_response_is_not_replayed_but_new_interaction_works(setup):
    session, sender = setup
    sender.fail = True
    with pytest.raises(RuntimeError):
        main.process_update(tg(1), session)
    sender.fail = False
    assert main.process_update(tg(1), session)["duplicate"]
    assert len(sender.sent) == 1
    assert main.process_update(tg(2), session)["temporary_entry"]
    assert len(sender.sent) == 2
    assert session.scalar(select(TrackingEvent).where(TrackingEvent.event_type == "temporary_intensive_entry")).metadata_json["delivery_status"] == "uncertain"


def test_scheduler_and_manual_advance_cannot_resume_marketing(setup):
    session, sender = setup
    main.process_update(tg(1), session)
    contact = session.scalar(select(Contact))
    run = start_run(session, contact.id, WELCOME_CODE)
    run.status = "error"
    session.commit()
    assert pause_marketing(session) == 1
    assert run.status == "paused"
    run.status = "active"
    sender.sent.clear()
    advance_run(session, run, sender)
    assert run.status == "paused" and not sender.sent
    assert run.context["paused_reason"] == "temporary_intensive_entry"


def test_broadcasts_suspended(setup):
    session, sender = setup
    row = SimpleNamespace(status="scheduled")
    assert main._deliver_broadcast(session, row, sender) == (0, 0)
    assert row.status == "paused" and not sender.sent


def test_scheduler_parks_future_marketing(setup, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from app.models import Broadcast, ContentItem
    session, sender = setup
    main.process_update(tg(1), session)
    contact = session.scalar(select(Contact))
    run = start_run(session, contact.id, WELCOME_CODE)
    run.status = "waiting"
    run.next_action_at = datetime.now(UTC) + timedelta(days=20)
    item = session.scalar(select(ContentItem).where(ContentItem.code == CONTENT_CODE))
    broadcast = Broadcast(title="Отложенная рассылка", content_item_id=item.id, status="scheduled", scheduled_at=run.next_action_at)
    session.add(broadcast)
    session.commit()
    class BorrowSession:
        def __enter__(self):
            return session
        def __exit__(self, *args):
            # Real SessionLocal closes and rolls back uncommitted state.
            session.rollback()
            session.expire_all()
    monkeypatch.setattr(main, "SessionLocal", BorrowSession)
    monkeypatch.setattr(main.settings, "telegram_test_bot_token", "")
    monkeypatch.setattr(main.settings, "max_bot_token", "")
    sender.sent.clear()
    main.scheduler_iteration()
    assert run.status == "paused" and broadcast.status == "paused" and not sender.sent
    monkeypatch.setattr(main.settings, "temporary_intensive_entry_enabled", False)
    main.scheduler_iteration()
    assert run.status == "paused" and broadcast.status == "paused" and not sender.sent


def test_draft_content_cannot_send_and_remains_in_audit(setup):
    from app.content_authoring import audit_content
    from app.models import ContentItem
    session, sender = setup
    item = session.scalar(select(ContentItem).where(ContentItem.code == CONTENT_CODE))
    item.editorial_status = "draft"
    session.commit()
    with pytest.raises(RuntimeError, match="not approved"):
        main.process_update(tg(1), session)
    assert not sender.sent
    assert any(row["code"] == CONTENT_CODE for row in audit_content(session)["items"])


def test_telegram_group_does_not_receive_personal_invitation(setup):
    session, sender = setup
    event = tg(1)
    event["message"]["chat"]["type"] = "group"
    main.process_update(event, session)
    assert not sender.sent


def test_max_service_and_self_events_are_not_answered(setup):
    session, sender = setup
    for e in [max_event(1, "bot_stopped"), {"update_type": "message_created", "message": {"sender": {"user_id": 5101, "is_bot": True}}}]:
        run_max(session, sender, e)
    assert not sender.sent
