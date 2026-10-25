from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import select

from app import app_routes
from app.account_auth_routes import ACCOUNT_MANAGER_EMAIL, COOKIE_NAME
from app.models import MessengerAccount, MessengerLinkToken, StrengthState, UserEmail
from test_strength_delivery import api  # noqa: F401


@pytest.fixture
def native(api, monkeypatch):
    client, factory, uid, other_id, sent, body = api
    monkeypatch.setattr(app_routes, "require_user_resource", lambda db, user, resource: user)
    monkeypatch.setattr(app_routes, "application_access_state", lambda *args: {"start_open": True})
    client.cookies.set(COOKIE_NAME, "synthetic-session")
    return client, factory, uid, other_id


def test_user_cannot_change_coach_comment_even_with_direct_request(native):
    client, factory, uid, _ = native
    with factory() as db:
        state = db.scalar(select(StrengthState).where(StrengthState.user_id == UUID(uid)))
        session = deepcopy(state.workouts[0])
        original = session["exercises"][0]["coach_note"]
    session["exercises"][0].update(coach_note="Подмена", note="Мой комментарий")
    response = client.post('/api/apps/strength', json={"action":"saveSession", "version":4,
                            "workout_type":2, "session":session})
    assert response.json()["ok"] is True
    with factory() as db:
        saved = db.scalar(select(StrengthState).where(StrengthState.user_id == UUID(uid))).workouts[0]["exercises"][0]
        assert saved["coach_note"] == original
        assert saved["note"] == "Мой комментарий"


def test_server_capability_and_client_picker_for_user_and_owner(native):
    client, factory, uid, other_id = native
    assert client.get('/api/apps/strength', params={"action":"openUser"}).json()["user"]["can_coach"] is False
    assert client.get('/api/apps/strength', params={"action":"openUser"}).json()["user"]["can_calculate_progression"] is False
    assert client.get('/api/apps/manager/context').json()["can_manage"] is False
    assert client.get('/api/apps/manager/users').status_code == 401
    assert client.get('/api/apps/strength', params={"action":"openUser", "target_user_id":other_id}).status_code == 401
    with factory() as db:
        email = db.scalar(select(UserEmail).where(UserEmail.user_id == UUID(uid)))
        email.email_normalized = ACCOUNT_MANAGER_EMAIL
        db.commit()
    for target in ({}, {"target_user_id":other_id}):
        assert client.get('/api/apps/strength', params={"action":"openUser", **target}).json()["user"]["can_coach"] is True
        assert client.get('/api/apps/strength', params={"action":"openUser", **target}).json()["user"]["can_calculate_progression"] is True
    assert client.get('/api/apps/manager/context').json()["can_manage"] is True
    assert client.get('/api/apps/strength', params={"action":"messengerState"}).json()["ok"] is True


def test_link_state_token_and_preference_use_the_authenticated_profile(native, monkeypatch):
    client, factory, uid, other_id = native
    settings = app_routes.get_settings()
    monkeypatch.setattr(settings, "account_telegram_bot_username", "test_link_bot")
    summary = client.get('/api/apps/strength', params={"action":"messengerState"}).json()
    assert summary["require_link"] is True and summary["destination"] is None
    assert client.get('/api/apps/strength', params={"action":"messengerState", "target_user_id":other_id}).status_code == 401
    assert client.get('/api/apps/strength', params={"action":"createMessengerLink", "platform":"telegram"}).status_code == 405
    result = client.post('/api/apps/strength', json={"action":"createMessengerLink", "platform":"telegram"}).json()
    assert result["deep_link"].startswith('https://t.me/test_link_bot?start=M')
    with factory() as db:
        token = db.scalar(select(MessengerLinkToken))
        assert str(token.user_id) == uid and token.purpose == "link_account"
        db.add(MessengerAccount(user_id=UUID(uid), platform="telegram", platform_user_id="test-tg", source="test",
                                linked_at=datetime.now(timezone.utc), is_deliverable=True, is_preferred=True))
        db.commit()
    summary = client.get('/api/apps/strength', params={"action":"messengerState"}).json()
    assert summary["destination"] == "telegram" and summary["require_link"] is False
    assert summary["bot_links"]["telegram"] == 'https://t.me/test_link_bot'
    response = client.post('/api/apps/strength', json={"action":"preferMessenger", "platform":"max"})
    assert response.status_code == 409
