import copy
import io
import json
import os
import urllib.error

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, strength_telegram as export
from app.config import Settings, get_settings
from app.database import Base, get_db
from app.models import AdminAppEdit, StrengthState, User


def workout(sets=None):
    return {"session_id": "synthetic-upper", "session_number": 11, "workout_type": 1, "date": "",
            "exercises": [{"exercise_id": "press", "exercise_name": "Жим <тест>", "note": "Пробный вес",
                           "sets": sets if sets is not None else [{"plan_weight": 40, "plan_reps": 12}]}]}


def test_plan_and_fact_are_selected_without_mutating_source():
    source = workout()
    before = copy.deepcopy(source)
    message = "\n".join(export.workout_messages("Профиль", source))
    assert "· План" in message and "40 кг × 12" in message and "не назначена" in message
    assert "Пробный вес" in message and "Жим <тест>" in message
    assert source == before
    source["exercises"][0]["sets"] = [
        {"plan_weight": 40, "plan_reps": 12, "fact_weight": 0, "fact_reps": 10, "rpe": 8},
        {"plan_weight": 50, "plan_reps": 15},
        {"plan_weight": 60, "plan_reps": 9, "rpe": 7},
        {"plan_weight": 70, "plan_reps": 8, "fact_weight": 65},
        {"plan_weight": 80, "plan_reps": 6, "completed": True},
    ]
    message = "\n".join(export.workout_messages("Профиль", source))
    assert "· Факт" in message and "0 кг × 10 · RPE 8" in message
    assert "50 кг" not in message
    assert "60 кг × 9 · RPE 7" in message and "65 кг × —" in message and "80 кг × 6" in message


def test_empty_export_is_rejected_and_example_and_long_notes_are_preserved():
    with pytest.raises(ValueError):
        export.workout_messages("Профиль", workout([]))
    source = workout()
    source["source"] = "model_example_at_owner_request"
    note = "Заметка 🏋️ " * 1000
    source["exercises"][0]["note"] = note
    messages = export.workout_messages("Профиль", source)
    assert len(messages) > 1
    assert all(len(message.encode("utf-16-le")) // 2 <= 4096 for message in messages)
    assert all("ID: synthetic-upper" in message for message in messages)
    content = "".join(message.split("\n\n", 1)[1] for message in messages)
    assert note in content and "не подтверждённый результат" in content


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", admin_username="owner", admin_password="test-password",
                        telegram_test_bot_token="123:secret-test", strength_telegram_owner_id="10001")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(export.router)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: settings
    with factory() as db:
        user = User(display_name="Синтетический профиль", status="active")
        db.add(user)
        db.flush()
        db.add(StrengthState(user_id=user.id, version=3, workout_types=[], hidden_exercises=[], workouts=[workout()]))
        db.commit()
        uid = str(user.id)
    sent = []
    def urlopen(request, timeout):
        sent.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"ok": True, "result": {"message_id": 77}}).encode())
    monkeypatch.setattr(export.urllib.request, "urlopen", urlopen)
    yield TestClient(app), factory, settings, sent, {"target_user_id": uid, "session_id": "synthetic-upper", "version": 3}
    engine.dispose()


def test_admin_sends_saved_profile_to_fixed_owner_and_records_audit(api):
    client, factory, settings, sent, body = api
    body["chat_id"] = "99999"
    response = client.post("/admin/api/apps/strength/telegram", json=body, auth=("owner", "test-password"))
    assert response.status_code == 200 and response.json()["message_ids"] == [77]
    assert len(sent) == 1 and sent[0]["chat_id"] == "10001"
    assert "Синтетический профиль" in sent[0]["text"] and "parse_mode" not in sent[0]
    with factory() as db:
        state = db.scalar(select(StrengthState))
        assert state.workouts == [workout()] and state.version == 3
        audit = db.scalar(select(AdminAppEdit))
        assert audit.action == "sendTelegram" and audit.details["message_ids"] == [77]


@pytest.mark.parametrize("change,expected", [({}, 401), ({"version": 2}, 409), ({"session_id": "missing"}, 404)])
def test_unauthenticated_or_stale_or_missing_export_never_sends(api, change, expected):
    client, _, _, sent, body = api
    body.update(change)
    response = client.post("/admin/api/apps/strength/telegram", json=body,
                           auth=("owner", "test-password") if change else None)
    assert response.status_code == expected and not sent


def test_unconfigured_recipient_and_transport_error_are_safe(api, monkeypatch):
    client, factory, settings, sent, body = api
    settings.strength_telegram_owner_id = "-10001"
    response = client.post("/admin/api/apps/strength/telegram", json=body, auth=("owner", "test-password"))
    assert response.status_code == 503 and not sent
    settings.strength_telegram_owner_id = "10001"
    def failure(*args, **kwargs):
        raise urllib.error.URLError("secret-test")
    monkeypatch.setattr(export.urllib.request, "urlopen", failure)
    response = client.post("/admin/api/apps/strength/telegram", json=body, auth=("owner", "test-password"))
    assert response.status_code == 502 and "secret-test" not in response.text
    with factory() as db:
        assert db.scalar(select(AdminAppEdit)) is None
