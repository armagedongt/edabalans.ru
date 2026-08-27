from __future__ import annotations

import httpx
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import content_authoring_cli
from app.content_authoring import audit_content
from app.content_formatting import template_value_for_source, validate_telegram_html
from app.database import Base, get_db, make_engine
from app.main import app
from app.masterclass_dispatch import content_is_sendable, rendered
from app.models import BotInstance, Contact, ContentItem, Sequence, SequenceStep, SequenceVersion
from app.seed import _add_missing_trigger_slots, seed_defaults
from app.start_router import send_system_content
from app.telegram import TelegramClient


def test_seed_gives_every_working_message_a_brief_and_writer_queue(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'content.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        report = audit_content(session)

    assert report["total"] == 46
    assert not [item for item in report["items"] if "missing_brief" in item["issues"]]
    assert not [item for item in report["items"] if item["editorial_status"] == "missing_content"]
    assert report["counts"]["placeholder"] == 27
    assert report["counts"]["approved"] == 19
    assert len(report["writer_queue"]) == 27
    assert report["approved_skipped"] == 19
    assert report["runtime_blocked"] == 27
    start_item = next(item for item in report["items"] if item.get("code") == "tpl_start_has_masterclass")
    assert start_item["usages"][0]["previous"]
    assert start_item["usages"][0]["next"]


def test_audit_reports_enabled_message_step_without_content(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'missing.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        sequence = session.scalar(select(Sequence).where(Sequence.code == "welcome_intensive"))
        version = session.scalar(
            select(SequenceVersion)
            .where(SequenceVersion.sequence_id == sequence.id, SequenceVersion.status == "published")
            .order_by(SequenceVersion.version_no.desc())
        )
        step = session.scalar(
            select(SequenceStep).where(
                SequenceStep.sequence_version_id == version.id,
                SequenceStep.kind == "MESSAGE",
            )
        )
        step.content_item_id = None
        session.commit()
        report = audit_content(session)

    missing = [item for item in report["items"] if item["editorial_status"] == "missing_content"]
    assert len(missing) == 1
    assert missing[0]["missing_reference"].startswith("__missing__:welcome_intensive:")


def test_new_text_trigger_gets_an_empty_writer_slot_by_default():
    trigger = {
        "step_key": "new_trigger",
        "content_code": "tpl_new_trigger_message",
        "title": "Новый trigger — сообщение",
        "trigger": "new_event",
        "condition": "Событие подтверждено",
        "recipient": "Клиент",
        "purpose": "Объяснить следующее действие.",
    }
    rows = _add_missing_trigger_slots([], [trigger])
    assert rows == [{
        "code": "new_trigger_message",
        "title": "Новый trigger — сообщение",
        "body": "",
        "media": None,
        "labels": ["автослот", "требуется текст", "после покупки"],
    }]


def test_confirmed_publish_is_versioned_and_skipped_by_writer(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'publish.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_day1"))
        version = item.content_version

    def db_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    client = TestClient(app)
    response = client.put(
        "/bot-api/content/tpl_day1/publish",
        json={
            "expected_version": version,
            "body_source": "<b>День 1</b>\n\nПервый готовый материал.",
            "purpose": "Дать первый материал интенсива.",
            "writer_brief": "Утверждённый материал первого дня; не менять без прямой команды.",
            "confirm": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["editorial_status"] == "approved"
    assert response.json()["content_version"] == version + 1
    conflict = client.put(
        "/bot-api/content/tpl_day1/publish",
        json={
            "expected_version": version,
            "body_source": "Другой текст",
            "purpose": "Цель",
            "writer_brief": "ТЗ",
            "confirm": True,
        },
    )
    assert conflict.status_code == 409
    report = client.get("/bot-api/content-audit").json()
    assert "tpl_day1" not in {item["code"] for item in report["writer_queue"]}
    assert report["approved_skipped"] == 20
    app.dependency_overrides.clear()


def test_admin_cannot_mark_placeholder_as_approved(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'approve.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_day2"))
        item_id = item.id

    def db_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    response = TestClient(app).patch(
        f"/bot-api/content/{item_id}", json={"editorial_status": "approved"}
    )
    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_admin_approved_edit_becomes_runtime_published(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'admin-publish.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_day2"))
        item_id, version = item.id, item.content_version

    def db_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    response = TestClient(app).patch(
        f"/bot-api/content/{item_id}",
        json={
            "expected_version": version,
            "body_source": "Готовый День 2",
            "purpose": "Дать второй день.",
            "writer_brief": "Утверждённый материал второго дня.",
            "editorial_status": "approved",
        },
    )
    assert response.status_code == 200
    assert response.json()["runtime_status"] == "published"
    app.dependency_overrides.clear()


def test_telegram_html_validator_accepts_supported_markup_and_templates():
    source = '<b>Важно</b>: <a href="{{account_url}}">открыть</a> <tg-spoiler>подсказка</tg-spoiler>'
    validate_telegram_html(source)
    assert template_value_for_source("<b>Анкета</b>", "telegram_html") == "<b>Анкета</b>"


@pytest.mark.parametrize("source", [
    '<script>alert(1)</script>',
    '<a href="javascript:alert(1)">ссылка</a>',
    '<b>не закрыто',
    '<b onclick="alert(1)">текст</b>',
    'еда & спорт',
    'текст &bogus;',
    'текст &nbsp;',
])
def test_telegram_html_validator_rejects_unsupported_html(source):
    with pytest.raises(ValueError):
        validate_telegram_html(source)


def test_publish_rejects_unknown_variable_and_oversized_text(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'validation.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_day3"))
        version = item.content_version

    def db_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    client = TestClient(app)
    common = {
        "expected_version": version,
        "purpose": "Цель",
        "writer_brief": "ТЗ",
        "confirm": True,
    }
    unknown = client.put(
        "/bot-api/content/tpl_day3/publish",
        json={**common, "body_source": "Текст {{unknown_value}}"},
    )
    assert unknown.status_code == 422
    oversized = client.put(
        "/bot-api/content/tpl_day3/publish",
        json={**common, "body_source": "а" * 4097},
    )
    assert oversized.status_code == 422
    blank_brief = client.put(
        "/bot-api/content/tpl_day3/publish",
        json={**common, "body_source": "Готовый текст", "writer_brief": "   "},
    )
    assert blank_brief.status_code == 422
    unsafe_html = client.put(
        "/bot-api/content/tpl_day3/publish",
        json={**common, "body_source": '<a href="javascript:alert(1)">Открыть</a>'},
    )
    assert unsafe_html.status_code == 422
    app.dependency_overrides.clear()


def test_validate_endpoint_runs_publish_checks_without_writing(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'check.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_day3"))
        version, original = item.content_version, item.body_source

    def db_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    client = TestClient(app)
    payload = {"expected_version": version, "body_source": "Текст {{unknown}}", "purpose": "Цель", "writer_brief": "ТЗ"}
    assert client.post("/bot-api/content/tpl_day3/validate", json=payload).status_code == 422
    payload["body_source"] = "<b>Готовый</b> текст"
    assert client.post("/bot-api/content/tpl_day3/validate", json=payload).json()["ok"] is True
    with Session(engine) as session:
        item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_day3"))
        assert (item.content_version, item.body_source) == (version, original)
    app.dependency_overrides.clear()


def test_status_only_approval_revalidates_saved_html(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'status-only.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_day3"))
        item.body_source = "еда & спорт"
        item.editorial_status = "draft"
        item.purpose = "Дать третий день"
        item.writer_brief = "Готовый полезный материал"
        item.status = "draft"
        item_id = item.id
        session.commit()

    def db_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    response = TestClient(app).patch(
        f"/bot-api/content/{item_id}",
        json={"editorial_status": "approved"},
    )
    assert response.status_code == 422
    assert "Некорректный Telegram HTML" in response.text
    app.dependency_overrides.clear()


def test_approved_html_link_is_not_treated_as_placeholder():
    item = ContentItem(
        code="tpl_link",
        title="Link",
        body_source='<a href="https://example.com">Открыть материал</a>',
        source_format="telegram_html",
        status="published",
        editorial_status="approved",
        purpose="Открыть материал",
        writer_brief="Сохранить ссылку",
    )
    assert content_is_sendable(item, item.body_source) == (True, None)


def test_runtime_rejects_invalid_approved_telegram_html():
    item = ContentItem(
        code="tpl_invalid",
        title="Invalid",
        body_source="еда & спорт",
        source_format="telegram_html",
        status="published",
        editorial_status="approved",
        purpose="Проверить защиту runtime",
        writer_brief="Некорректный HTML не отправлять",
    )
    assert content_is_sendable(item, item.body_source) == (False, "content has invalid Telegram HTML")


def test_seed_content_change_increments_optimistic_version(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'seed-version.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_start_intensive_waiting"))
        item.body_source = "Интенсив уже идёт 👍 старый seed"
        version = item.content_version
        session.commit()
        seed_defaults(session, "Fitness_Talks_bot")
        session.refresh(item)
        assert item.content_version == version + 1
        assert item.body_source.startswith("Посты интенсива")


def test_runtime_html_fragment_reaches_telegram_without_format_conversion():
    item = ContentItem(
        code="tpl_runtime",
        title="Runtime",
        body_source="<b>Анкета</b>\n\n{{questionnaire_formatted}}",
        source_format="telegram_html",
        status="published",
        editorial_status="approved",
    )
    content = rendered(item, {"questionnaire_formatted": "<b>Ответ</b> — да"})
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

    TelegramClient("secret", httpx.MockTransport(handler)).send_content("42", content, {})
    assert json.loads(seen[0].read())["text"] == "<b>Анкета</b>\n\n<b>Ответ</b> — да"


def test_start_router_rejects_unapproved_system_content(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'start-gate.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "Fitness_Talks_bot")
        item = session.scalar(select(ContentItem).where(ContentItem.code == "tpl_start_navigation_pin"))
        item.editorial_status = "draft"
        bot = session.scalar(select(BotInstance))
        recipient = Contact(bot_instance_id=bot.id, telegram_user_id="42", chat_id="42")
        session.add(recipient); session.flush()

        class Sender:
            def send_content(self, *_):
                raise AssertionError("unapproved content must not be sent")

        with pytest.raises(RuntimeError, match="not owner-approved"):
            send_system_content(session, recipient, item.code, Sender())


def test_chat_working_file_preserves_metadata_and_publishes_confirmed(tmp_path, monkeypatch):
    module = content_authoring_cli
    item = {
        "code": "tpl_start_navigation_pin",
        "content_version": 4,
        "editorial_status": "approved",
        "purpose": "Навигация",
        "writer_brief": "Сохранить четыре пункта.",
        "body_source": "<b>legacy</b>",
        "html_source": "<b>Навигация</b>",
        "usages": [{"module": "start_attribution", "previous": "Start", "step": "Навигация", "next": "Welcome"}],
    }
    working = tmp_path / "message.telegram-html.txt"
    working.write_text(module.render_working_file(item), encoding="utf-8")
    parsed = module.parse_working_file(working)
    assert parsed == {
        "code": "tpl_start_navigation_pin",
        "expected_version": 4,
        "purpose": "Навигация",
        "writer_brief": "Сохранить четыре пункта.",
        "body_source": "<b>Навигация</b>",
    }
    calls = []
    monkeypatch.setattr(module, "api_request", lambda args, method, path, payload=None: calls.append((method, path, payload)) or {"ok": True})
    monkeypatch.setattr(module.sys, "argv", ["publish_telegram_message.py", "publish", str(working)])
    assert module.main() == 0
    assert calls[0][0] == "PUT"
    assert calls[0][2]["confirm"] is True
    calls.clear()
    monkeypatch.setattr(module.sys, "argv", ["publish_telegram_message.py", "check", str(working)])
    assert module.main() == 0
    assert calls[0][0:2] == ("POST", "/bot-api/content/tpl_start_navigation_pin/validate")
    assert "confirm" not in calls[0][2]


def test_media_only_video_note_working_file_can_be_parsed(tmp_path):
    module = content_authoring_cli
    item = {
        "code": "tpl_entry_circle",
        "content_version": 1,
        "editorial_status": "approved",
        "purpose": "Познакомить с Сергеем.",
        "writer_brief": "Утверждённый видеокружок без подписи.",
        "body_source": "",
        "html_source": "",
        "media_kind": "video_note",
    }
    working = tmp_path / "circle.telegram-html.txt"
    working.write_text(module.render_working_file(item), encoding="utf-8")
    assert module.parse_working_file(working)["body_source"] == ""
