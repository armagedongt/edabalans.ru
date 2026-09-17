from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from test_masterclass_journey import setup, teardown_function
from app.models import CourseStageProgress, QuestionnaireAnswer, QuestionnaireRun, Resource, User, UserAccess, UserEmail


def test_person_answers_are_typed_persisted_and_shared_only_with_own_calculator():
    client, factory = setup()
    opened = client.get("/api/masterclass/questionnaires/onboarding?email=member@example.test").json()
    assert opened["personParameters"] == {}
    values = {"person_gender": "Женщина", "person_age": "35", "person_height": "170", "person_weight": "80,5"}
    for code, text in values.items():
        response = client.put("/api/masterclass/questionnaires/onboarding/answer", json={"email": "member@example.test", "question_code": code, "answer_text": text})
        assert response.status_code == 200
    expected = {"gender": "Женщина", "age": 35, "height": 170, "weight": 80.5}
    assert client.get("/api/masterclass/questionnaires/onboarding?email=member@example.test").json()["personParameters"] == expected
    assert client.get("/api/masterclass/questionnaires/onboarding?email=other@example.test").status_code == 403
    with factory() as db:
        other = User(display_name="Другой участник", status="active")
        db.add(other); db.flush()
        db.add(UserEmail(user_id=other.id, email_original="other@example.test", email_normalized="other@example.test", is_primary=True, source="test"))
        other_run = QuestionnaireRun(user_id=other.id, kind="onboarding")
        db.add(other_run); db.flush()
        for code, text in {"person_gender":"Мужчина", "person_age":"55", "person_height":"190", "person_weight":"110"}.items():
            db.add(QuestionnaireAnswer(run_id=other_run.id, question_code=code, answer_text=text))
        user_id = db.scalar(select(UserEmail.user_id).where(UserEmail.email_normalized == "member@example.test"))
        resource = Resource(code="ACCESS_CALORIES", name="Калорийный курс", status="active")
        db.add(resource); db.flush()
        db.add(UserAccess(user_id=user_id, resource_id=resource.id, source="test", granted_at=datetime.now(timezone.utc)))
        db.add(CourseStageProgress(user_id=user_id, course_code="calories", stage_number=2, completed_at=datetime.now(timezone.utc)))
        db.add(UserAccess(user_id=other.id, resource_id=resource.id, source="test", granted_at=datetime.now(timezone.utc)))
        db.add(CourseStageProgress(user_id=other.id, course_code="calories", stage_number=2, completed_at=datetime.now(timezone.utc)))
        db.commit()
    payload = client.get("/api/apps/metabolism").json()
    assert payload["ok"] is True
    assert payload["personParameters"] == expected
    assert payload["email"] == "member@example.test"
    own_account = client.get("/api/account-auth/account").json()
    assert next(item for item in own_account["applications"] if item["code"] == "metabolism")["state"] == "available"
    foreign_account = client.get("https://api.edabalans.ru/api/account?email=other@example.test").json()
    assert next(item for item in foreign_account["applications"] if item["code"] == "metabolism")["app"] is None
    assert next(item for item in foreign_account["applications"] if item["code"] == "metabolism")["state"] == "stage_locked"
    client.cookies.clear()
    anonymous = client.get("https://api.edabalans.ru/api/account?email=member@example.test")
    assert anonymous.status_code == 200
    assert next(item for item in anonymous.json()["applications"] if item["code"] == "metabolism")["state"] == "stage_locked", "legacy anonymous payload must not disclose completion"


@pytest.mark.parametrize("code,text", [("person_age", "35.5"), ("person_height", "NaN"), ("person_weight", "-5"), ("person_gender", "<script>")])
def test_invalid_person_value_does_not_replace_saved_value(code, text):
    client, _ = setup()
    body = {"email": "member@example.test", "question_code": code, "answer_text": text}
    assert client.put("/api/masterclass/questionnaires/onboarding/answer", json=body).status_code == 422
    assert client.get("/api/masterclass/questionnaires/onboarding?email=member@example.test").json()["personParameters"] == {}


def test_three_variants_round_trip_conflicts_and_archived_ui_preserves_third():
    client, factory = setup()
    with factory() as db:
        user_id = db.scalar(select(UserEmail.user_id).where(UserEmail.email_normalized == "member@example.test"))
        resource = Resource(code="ACCESS_CALORIES", name="Калорийный курс", status="active")
        db.add(resource); db.flush()
        db.add(UserAccess(user_id=user_id, resource_id=resource.id, source="test", granted_at=datetime.now(timezone.utc)))
        db.add(CourseStageProgress(user_id=user_id, course_code="calories", stage_number=2, completed_at=datetime.now(timezone.utc)))
        db.commit()
    initial = client.get("/api/apps/metabolism").json()
    variants = {"1": {"steps": 6000, "_name": "Исходный"}, "2": {"steps": 8000}, "3": {"steps": 10000, "_unit": "percent", "_percent": 10}}
    saved = client.put("/api/apps/metabolism", json={"version": initial["version"], "activeVariant": 3, "variants": variants})
    assert saved.status_code == 200
    loaded = client.get("/api/apps/metabolism").json()
    assert loaded["variants"] == variants
    assert loaded["activeVariant"] == 3
    stale = client.put("/api/apps/metabolism", json={"version": initial["version"], "activeVariant": 1, "variants": {"1": {"steps": 0}}})
    assert stale.status_code == 409
    assert client.get("/api/apps/metabolism").json()["variants"] == variants
    archived = client.put("/api/apps/metabolism", json={"version": loaded["version"], "activeVariant": 1, "variants": {"1": {"steps": 7000}, "2": {"steps": 9000}}})
    assert archived.status_code == 200
    after = client.get("/api/apps/metabolism").json()
    assert after["variants"]["3"] == variants["3"]
    assert after["variants"]["1"]["_name"] == "Исходный"
    legacy_deficit = client.put("/api/apps/metabolism", json={"version": after["version"], "activeVariant": 3, "variants": {"3": {"deficit": 500}}})
    assert legacy_deficit.status_code == 200
    restored = client.get("/api/apps/metabolism").json()["variants"]["3"]
    assert restored["deficit"] == 500
    assert restored["_unit"] == "kcal"
    assert restored["_percent"] == 0


def test_shared_questionnaire_assets_and_archived_app_are_served_by_real_backend():
    client, _ = setup()
    for name in ("questionnaire-person.js", "questionnaire-person.css"):
        response = client.get("/assets/" + name)
        assert response.status_code == 200
        assert "ed-person-fields" in response.text
    archived = client.get("/apps/metabolism-old.html")
    assert archived.status_code == 200
    assert 'id="metabolism-old-app"' in archived.text
