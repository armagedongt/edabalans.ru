from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.app_menu import APPS_PAYLOAD, REVEAL_EVENTS, STRENGTH_ADMIN_CONTENT_CODE, STRENGTH_ADMIN_PAYLOAD, Application, app_request, available_applications, menu_presentation
from app.database import Base, make_engine
from app.graph import apps_menu_graph
from app.models import Contact, ContentItem, CrmUser
from app.seed import _start_system_messages


def prepared(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'apps-menu.sqlite'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.execute(text("""
        CREATE TABLE resources (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL
        )
    """))
    session.execute(text("""
        CREATE TABLE user_accesses (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            expires_at TIMESTAMP NULL,
            revoked_at TIMESTAMP NULL
        )
    """))
    session.execute(text("""
        CREATE TABLE masterclass_events (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL
        )
    """))
    user = CrmUser(display_name="Участник", status="active", data_origin="native")
    session.add(user)
    session.flush()
    contact = Contact(
        bot_instance_id="bot",
        user_id=user.id,
        telegram_user_id="42",
        chat_id="42",
    )
    session.add(contact)
    session.add(ContentItem(
        code=STRENGTH_ADMIN_CONTENT_CODE,
        title="Админка тренировок — вход с телефона",
        body_source="<b>Админка тренировок</b>",
        source_format="telegram_html",
        status="published",
        purpose="Открыть владельцу мобильную админку тренировок.",
        writer_brief="Служебный вход владельца; не обещать пользовательский доступ.",
        editorial_status="approved",
    ))
    return session, user, contact


def grant(session, user, code, *, revoked=False, expired=False):
    resource_id = str(uuid4())
    session.execute(
        text("INSERT INTO resources (id, code, status) VALUES (:id, :code, 'active')"),
        {"id": resource_id, "code": code},
    )
    session.execute(text("""
        INSERT INTO user_accesses (id, user_id, resource_id, expires_at, revoked_at)
        VALUES (:id, :user_id, :resource_id, :expires_at, :revoked_at)
    """), {
        "id": str(uuid4()),
        "user_id": user.id,
        "resource_id": resource_id,
        "expires_at": datetime.now(UTC) - timedelta(minutes=1) if expired else None,
        "revoked_at": datetime.now(UTC) if revoked else None,
    })


def reveal(session, user, event_type):
    session.execute(
        text("INSERT INTO masterclass_events (id, user_id, event_type) VALUES (:id, :user_id, :event_type)"),
        {"id": str(uuid4()), "user_id": user.id, "event_type": event_type},
    )


def test_common_and_specific_deep_links_are_short_and_reserved():
    assert app_request("/start apps") == APPS_PAYLOAD
    requested = app_request("/start training")
    assert isinstance(requested, Application)
    assert requested.code == "strength"
    assert app_request("/apps") == APPS_PAYLOAD
    assert app_request("/start training_admin") == STRENGTH_ADMIN_PAYLOAD
    assert app_request("/start unrelated") is None


def test_strength_admin_deep_link_opens_protected_mobile_admin_for_current_profile(tmp_path):
    session, user, contact = prepared(tmp_path)
    try:
        requested = app_request("/start training_admin")
        content, configuration = menu_presentation(session, contact, requested)
        assert content.body_source.startswith("<b>Админка тренировок</b>")
        assert configuration["buttons"] == [{
            "text": "Открыть админку тренировок",
            "web_app": {
                "url": f"https://edabalans.ru/admin/strength?mobile=1&user={user.id}"
            },
        }]
    finally:
        session.close()


def test_strength_admin_message_is_an_editable_approved_slot_and_visible_in_graph(tmp_path):
    rows = {row["code"]: row for row in _start_system_messages()}
    assert rows["apps_strength_admin"]["body"].startswith("<b>Админка тренировок</b>")

    session, _, _ = prepared(tmp_path)
    try:
        item = session.scalar(select(ContentItem).where(ContentItem.code == STRENGTH_ADMIN_CONTENT_CODE))
        item.body_source = "Отредактированный текст входа"
        session.commit()

        content, _ = menu_presentation(session, session.query(Contact).one(), STRENGTH_ADMIN_PAYLOAD)
        assert content is item
        graph = apps_menu_graph(session)
        message = next(node for node in graph["nodes"] if node["id"] == "apps_admin_message")
        assert message["content"]["code"] == STRENGTH_ADMIN_CONTENT_CODE
        assert message["content"]["usages"] == [{
            "kind": "direct_trigger",
            "module": "apps_menu",
            "step": "training_admin",
            "previous": "Открыта служебная ссылка /start training_admin",
            "next": "Кнопка открывает защищённую мобильную админку тренировок",
        }]
        assert not graph["issues"]
    finally:
        session.close()


def test_strength_admin_does_not_send_unapproved_content(tmp_path):
    session, _, contact = prepared(tmp_path)
    try:
        item = session.scalar(select(ContentItem).where(ContentItem.code == STRENGTH_ADMIN_CONTENT_CODE))
        item.editorial_status = "draft"
        session.commit()
        with pytest.raises(RuntimeError, match="not owner-approved"):
            menu_presentation(session, contact, STRENGTH_ADMIN_PAYLOAD)
    finally:
        session.close()


def test_each_application_requires_only_its_explicit_course_reveal_event():
    assert REVEAL_EVENTS == {
        "dqs": {"app_revealed_dqs"},
        "strength": {"app_revealed_strength"},
        "metabolism": {"app_revealed_metabolism"},
        "recipes": {"app_revealed_recipes"},
    }


def test_menu_contains_only_current_active_entitlements(tmp_path):
    session, user, contact = prepared(tmp_path)
    try:
        grant(session, user, "dqs")
        grant(session, user, "ACCESS_CALORIES")
        grant(session, user, "strength", revoked=True)
        grant(session, user, "ACCESS_RECIPES", expired=True)
        reveal(session, user, "app_revealed_dqs")
        reveal(session, user, "app_revealed_metabolism")
        session.commit()

        applications = available_applications(session, user.id)
        assert [item.code for item in applications] == ["dqs", "metabolism"]
        content, configuration = menu_presentation(session, contact)
        assert content.body_source.startswith("<b>Мои приложения</b>\n\n")
        assert [button["text"] for button in configuration["buttons"]] == [
            "Оценка качества питания",
            "Калькулятор метаболизма",
            "Обновить",
        ]
    finally:
        session.close()


def test_specific_app_link_denies_without_entitlement_and_uses_first_person_support(tmp_path):
    session, _, contact = prepared(tmp_path)
    try:
        requested = app_request("/start dqs")
        assert isinstance(requested, Application)
        content, configuration = menu_presentation(session, contact, requested)
        assert "нет доступа" in content.body_source
        assert "напишите мне" in content.body_source
        assert configuration["buttons"] == [{"text": "Написать мне", "url": "https://t.me/FitnessSergey"}]
    finally:
        session.close()


def test_inactive_user_never_gets_app_buttons(tmp_path):
    session, user, _ = prepared(tmp_path)
    try:
        grant(session, user, "dqs")
        reveal(session, user, "app_revealed_dqs")
        user.status = "blocked"
        session.commit()
        assert available_applications(session, user.id) == []
    finally:
        session.close()


def test_paid_entitlement_stays_hidden_until_course_reveal(tmp_path):
    session, user, contact = prepared(tmp_path)
    try:
        grant(session, user, "dqs")
        reveal(session, user, "dqs_opened")
        session.commit()
        assert available_applications(session, user.id) == []

        reveal(session, user, "app_revealed_dqs")
        session.commit()
        assert [item.code for item in available_applications(session, user.id)] == ["dqs"]
        _, configuration = menu_presentation(session, contact)
        assert configuration["buttons"][0]["max_app_payload"] == "dqs"
    finally:
        session.close()
