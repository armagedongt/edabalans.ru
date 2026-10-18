from types import SimpleNamespace
import json

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.main as main
from app.database import Base, make_engine
from app.models import Contact, ContentItem, SequenceRun
from app.public_menu import COMMAND_CONTENT, configure_commands, seed_public_menu
from app.seed import seed_defaults
from app.telegram import TelegramClient


@pytest.fixture
def menu(tmp_path, monkeypatch):
    db = make_engine(f"sqlite:///{tmp_path / 'menu.sqlite'}")
    Base.metadata.create_all(db)
    session = Session(db)
    seed_defaults(session, "Fitness_Talks_bot")
    monkeypatch.setattr(main.settings, "temporary_intensive_entry_enabled", True)
    sent = []
    def transport(request):
        sent.append((request.url.path.rsplit('/', 1)[-1], json.loads(request.content)))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(sent)}})
    sender = TelegramClient("test", httpx.MockTransport(transport))
    monkeypatch.setattr(main, "client", lambda: sender)
    yield session, sent
    session.close()
    db.dispose()


def update(n, command):
    return {"update_id": n, "message": {"message_id": n, "from": {"id": 42}, "chat": {"id": 42, "type": "private"}, "text": command}}


@pytest.mark.parametrize("command", ["/channel", "/mk", "/contact"])
def test_navigation_sends_only_requested_text_without_article_or_buttons(menu, command):
    session, sent = menu
    result = main.process_update(update(1, command), session)
    assert result["menu_command"] == command
    assert len(sent) == 1
    method, payload = sent[0]
    assert method == "sendMessage"
    assert "reply_markup" not in payload
    assert payload["disable_web_page_preview"] is True
    assert "{{" not in payload["text"]
    if command in {"/channel", "/contact"}:
        assert "Навигация!" in payload["text"]
    if command == "/mk":
        assert 'href="https://' in payload["text"]
        assert '>похудение-это-есть.рф</a>' in payload["text"]
    assert session.scalar(select(func.count()).select_from(SequenceRun)) == 0
    assert main.process_update(update(1, command), session)["duplicate"]
    assert len(sent) == 1


def test_stop_navigation_and_resume_do_not_replay_welcome(menu, monkeypatch):
    session, sent = menu
    main.process_update(update(1, "/stop"), session)
    contact = session.scalar(select(Contact).where(Contact.telegram_user_id == "42"))
    assert contact.status == "stopped"
    assert "/resume" in sent[-1][1]["text"]
    monkeypatch.setattr(main.settings, "temporary_intensive_entry_enabled", False)
    main.process_update(update(2, "/contact"), session)
    assert contact.status == "stopped"
    main.process_update(update(3, "/resume"), session)
    assert contact.status == "active"
    assert len(sent) == 3
    assert session.scalar(select(func.count()).select_from(SequenceRun)) == 0


def test_resume_does_not_unblock_contact(menu):
    session, sent = menu
    main.process_update(update(1, "/contact"), session)
    contact = session.scalar(select(Contact).where(Contact.telegram_user_id == "42"))
    contact.status = "blocked"
    session.commit()
    main.process_update(update(2, "/stop"), session)
    assert main.process_update(update(3, "/resume"), session)["excluded"]
    assert contact.status == "blocked"
    assert len(sent) == 2


def test_resume_keeps_existing_stopped_sequence_completed(menu):
    session, sent = menu
    from app.engine import start_run
    main.process_update(update(1, "/contact"), session)
    contact = session.scalar(select(Contact).where(Contact.telegram_user_id == "42"))
    run = start_run(session, contact.id, "welcome_intensive")
    session.commit()
    assert run.status in {"active", "waiting"}
    main.process_update(update(2, "/stop"), session)
    assert run.status == "completed" and run.next_action_at is None
    main.process_update(update(3, "/resume"), session)
    assert run.status == "completed" and run.next_action_at is None
    assert session.scalar(select(func.count()).select_from(SequenceRun)) == 1
    assert len(sent) == 3


def test_guide_uses_same_temporary_start_path(menu):
    session, sent = menu
    assert main.process_update(update(1, "/guide"), session)["temporary_entry"]
    assert [method for method, _ in sent] == ["sendMessage", "pinChatMessage", "sendVideo"]
    assert main.process_update(update(2, "/start"), session)["temporary_entry"]
    assert sent[-1][0] == "sendVideo"
    events = list(session.scalars(select(main.TrackingEvent).where(main.TrackingEvent.event_type == "start_maintenance")))
    assert len(events) == 2


def test_command_registration_hides_start_and_resume():
    calls = []
    configure_commands(SimpleNamespace(call=lambda method, payload: calls.append((method, payload))))
    for method, payload in calls[:2]:
        assert method == "setMyCommands"
        assert [row["command"] for row in payload["commands"]] == ["guide", "mk", "channel", "contact", "stop"]
    assert calls[-1] == ("setChatMenuButton", {"menu_button": {"type": "commands"}})


def test_seed_preserves_later_owner_copy_and_slots_are_editable(menu):
    session, _ = menu
    item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_menu_masterclass"))
    item.body_source = "Изменённый владельцем текст"
    session.commit()
    seed_public_menu(session)
    assert item.body_source == "Изменённый владельцем текст"
    from app.content_authoring import content_usages
    usages = content_usages(session)
    assert all(row[0] in usages for row in COMMAND_CONTENT.values())


def test_channel_and_contact_follow_live_navigation_edits(menu):
    session, sent = menu
    item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_onepage_entry_navigation"))
    item.body_source = 'Первая навигация <a href="{{personal_intensive_url}}">Статья</a>'
    session.commit()
    main.process_update(update(1, "/channel"), session)
    assert sent[-1][1]["text"].startswith("Первая навигация")
    assert "{{" not in sent[-1][1]["text"]
    item.body_source = "Новая навигация после редакции"
    session.commit()
    main.process_update(update(2, "/contact"), session)
    main.process_update(update(3, "/channel"), session)
    assert [payload["text"] for _, payload in sent[1:]] == [item.body_source, item.body_source]
    assert len(sent) == 3
    assert session.scalar(select(func.count()).select_from(SequenceRun)) == 0


@pytest.mark.parametrize("old,new", [("/masterclass", "/mk"), ("/contacts", "/contact")])
def test_previous_commands_remain_hidden_aliases(menu, old, new):
    session, sent = menu
    assert main.process_update(update(1, old), session)["menu_command"] == new
    assert len(sent) == 1


@pytest.mark.parametrize("prepared", [True, False])
def test_menu_and_start_use_same_prepared_navigation(menu, prepared):
    session, sent = menu
    from app.onepage_campaign import ENTRY_CODES, SKIP
    code = ENTRY_CODES["tg"]["navigation"]
    item = ContentItem(code=code, title="Подготовленная навигация", body_source="Новая навигация" if prepared else SKIP,
                       source_format="telegram_html", editorial_status="approved", status="published")
    session.add(item)
    session.commit()
    main.process_update(update(1, "/channel"), session)
    first = sent[-1][1]["text"]
    from app.graph import start_attribution_graph
    nodes = {node["id"]: node for node in start_attribution_graph(session)["nodes"]}
    expected_code = code if prepared else "tpl_onepage_entry_navigation"
    for node_id in ("menu_channel", "menu_contact", "temporary_navigation"):
        assert nodes[node_id]["content"]["code"] == expected_code
    main.process_update(update(2, "/start"), session)
    assert sent[1][0] == "sendMessage" and sent[1][1]["text"] == first
    if prepared:
        assert first == item.body_source
        item.body_source = "Изменённый актуальный закреп"
        session.commit()
        main.process_update(update(3, "/contact"), session)
        assert sent[-1][1]["text"] == item.body_source
        main.process_update(update(4, "/channel"), session)
        assert sent[-1][1]["text"] == item.body_source
    else:
        assert "Навигация!" in first and SKIP not in first
