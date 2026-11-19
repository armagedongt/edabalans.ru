import json
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import crm_routes
from app.database import get_db
from app.main import app
from app.models import DqsState, User
from test_admin_apps import login, make_client


@pytest.fixture
def diary(tmp_path, monkeypatch):
    monkeypatch.setattr(crm_routes, "PRIVATE_DIARY_DIR", tmp_path)
    client, factory = make_client()
    with factory() as db:
        user = User(display_name="Diary test")
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(DqsState(user_id=user_id, days={"1": {"p": [1], "d": [True]}}))
        db.commit()
    yield client, factory, user_id, tmp_path / f"{user_id}.json"
    app.dependency_overrides.pop(get_db, None)
    client.close()


def test_current_shared_diary_shows_known_fields_and_preserves_missing_and_dqs(diary):
    client, factory, user_id, path = diary
    path.write_text(json.dumps({"data": {"categories": [], "days": [
        {"date": "2026-11-09", "weight": 60, "kcal": 1900, "protein": 120, "fat": 60,
         "carbs": 220, "source": "report"},
        {"date": "2026-11-10", "steps": 0},
    ], "table_from": "2026-11-10"}, "prior_note_ids": []}), encoding="utf-8")
    url = f"/admin/api/users/{user_id}/diary"
    assert client.get(url).status_code == 401
    login(client)
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    days = response.json()["imported"]["days"]
    assert response.json()["imported"]["table_from"] == "2026-11-10"
    assert len(days) == 2  # Display filtering must not discard source records.
    assert (days[0]["weight"], days[0]["kcal"], days[0]["protein"], days[0]["fat"], days[0]["carbs"]) == (60, 1900, 120, 60, 220)
    assert days[0]["steps"] is None
    assert days[1]["steps"] == 0
    assert days[1]["weight"] is days[1]["kcal"] is days[1]["legacy_dqs"] is None
    with factory() as db:
        assert db.scalar(select(DqsState)).days == {"1": {"p": [1], "d": [True]}}
    assert client.get(f"/admin/api/users/{uuid.uuid4()}/diary").status_code == 404


def test_outdated_snapshot_remains_history_only(diary):
    client, _, user_id, path = diary
    path.write_text(json.dumps({"data": {"categories": ["Old"], "days": [
        {"date": "2025-11-09", "weight": 70, "steps": 5000, "steps_qualifier": ">",
         "activity": "run", "alcohol": "", "legacy_dqs": {
             "total": 2, "categories": [{"portions": 1, "score": 2, "variety": True}]}}
    ]}, "prior_note_ids": [], "outdated": True}), encoding="utf-8")
    login(client)
    url = f"/admin/api/users/{user_id}/diary"
    assert client.get(url).json()["imported"] is None
    historical = client.get(url + "?history=true").json()
    assert historical["history_outdated"] is True
    day = historical["imported"]["days"][0]
    assert day["steps_qualifier"] == ">"
    assert day["legacy_dqs"]["total"] == 2


def test_missing_and_corrupt_snapshot_preserve_dashboard(diary):
    client, _, user_id, path = diary
    login(client)
    url = f"/admin/api/users/{user_id}/diary"
    assert client.get(url).json()["imported"] is None
    assert client.get(url + "?history=true").status_code == 404
    path.write_text("not json", encoding="utf-8")
    assert client.get(url).json()["imported"] is None
    assert client.get(url + "?history=true").status_code == 503


@pytest.mark.parametrize("field,value", [("weight", 0), ("steps", -1), ("kcal", -1),
                                       ("protein", float("inf")), ("fat", -1), ("carbs", -1)])
def test_invalid_metric_is_rejected(field, value):
    with pytest.raises(ValidationError):
        crm_routes.ImportedDiaryDay.model_validate({"date": "2026-11-09", field: value})


def test_training_and_period_summaries_roundtrip_without_changing_dqs(diary):
    client, factory, user_id, path = diary
    session = {"start": "08:10", "type": "Swim", "moving_seconds": 3600,
               "elapsed_seconds": 4500, "kcal_total": 600, "kcal_active": 530,
               "active_estimated": True, "basal_kcal_day": 1344,
               "duration_basis": "elapsed", "source_url": "https://www.strava.com/activities/123"}
    summary = {"start": "2026-11-01", "end": "2026-11-07", "active": 500,
               "resting": 1500, "total": 2000, "source": "device screenshot"}
    path.write_text(json.dumps({"data": {"categories": [], "days": [
        {"date": "2026-11-01", "training_sessions": [session]}],
        "energy_summaries": [summary]}, "prior_note_ids": []}), encoding="utf-8")
    login(client)
    result = client.get(f"/admin/api/users/{user_id}/diary").json()["imported"]
    assert result["days"][0]["training_sessions"] == [session]
    assert result["energy_summaries"] == [summary]
    assert result["days"][0]["kcal"] is None
    with factory() as db:
        assert db.scalar(select(DqsState)).days == {"1": {"p": [1], "d": [True]}}


@pytest.mark.parametrize("change", [{"kcal_active": 601}, {"basal_kcal_day": None},
                                  {"source_url": "javascript:alert(1)"}, {"elapsed_seconds": -1}])
def test_invalid_training_cannot_be_loaded(change):
    session = {"start": "08:10", "type": "Swim", "moving_seconds": 3600,
               "elapsed_seconds": 4500, "kcal_total": 600, "kcal_active": 530,
               "active_estimated": True, "basal_kcal_day": 1344,
               "duration_basis": "elapsed", "source_url": "https://www.strava.com/activities/123", **change}
    with pytest.raises(ValidationError):
        crm_routes.DiaryTrainingSession.model_validate(session)
