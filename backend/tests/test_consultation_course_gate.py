from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from test_calorie_course_journey import setup, teardown_function
from app.access_service import course_start_is_open, course_waits_for_consultation
from app.course_access_service import course_entry_unlocked
from app.models import Resource, UserAccess, UserCoursePolicy, UserEmail


def configure(db, *, resource_code="ACCESS_CALORIES", mode="auto", consultation="active"):
    user_id = db.scalar(select(UserEmail.user_id).where(UserEmail.email_normalized == "calories@example.test"))
    resource = db.scalar(select(Resource).where(Resource.code == resource_code))
    if resource is None:
        resource = Resource(code=resource_code, name=resource_code, status="active")
        db.add(resource)
        db.flush()
    policy = None
    if mode is not None:
        policy = UserCoursePolicy(user_id=user_id, resource_id=resource.id, start_mode=mode, source="test")
        db.add(policy)
    if consultation != "absent":
        consult = Resource(code="ACCESS_CONSULTATION", name="Консультация", status="active")
        db.add(consult)
        db.flush()
        now = datetime.now(timezone.utc)
        access = UserAccess(user_id=user_id, resource_id=consult.id, source="test", granted_at=now)
        if consultation == "paused":
            access.paused_at = now
        elif consultation == "revoked":
            access.revoked_at = now
        elif consultation == "expired":
            access.expires_at = now - timedelta(days=1)
        elif consultation == "inactive_resource":
            consult.status = "inactive"
        db.add(access)
    db.commit()
    return user_id, policy


@pytest.mark.parametrize("resource_code", ["ACCESS_CALORIES", "ACCESS_STRENGTH"])
@pytest.mark.parametrize("mode,consultation,expected", [
    ("auto", "active", False),
    ("auto", "absent", True),
    ("auto", "paused", True),
    ("auto", "revoked", True),
    ("auto", "expired", True),
    ("auto", "inactive_resource", True),
    ("open", "active", True),
    ("blocked", "active", False),
    (None, "active", True),
])
def test_consultation_gate_respects_current_right_and_manual_or_legacy_policy(resource_code, mode, consultation, expected):
    client, factory = setup()
    try:
        with factory() as db:
            user_id, _ = configure(db, resource_code=resource_code, mode=mode, consultation=consultation)
            assert course_start_is_open(db, user_id, resource_code) is expected
            assert course_entry_unlocked(db, user_id, resource_code) is expected
    finally:
        client.close()
        factory.kw["bind"].dispose()


@pytest.mark.parametrize("masterclass_done", [False, True])
def test_manual_open_releases_course_but_does_not_mark_lessons_completed(monkeypatch, masterclass_done):
    client, factory = setup(masterclass_completed=masterclass_done)
    try:
        from app.product_catalog_service import PRODUCT_CONNECTIONS
        monkeypatch.setitem(PRODUCT_CONNECTIONS["calories"], "maintenance", False)
        with factory() as db:
            user_id, policy = configure(db)
            # Opening every lesson cannot silently bypass a consultation hold.
            policy.unlock_mode = "fully_unlocked"
            db.commit()
        for suffix in ("", "/manifest", "/materials"):
            response = client.get(f"/api/calories/course{suffix}", params={"email": "calories@example.test"})
            assert response.status_code == 403
            assert "после консультации" in response.json()["detail"]
        assert client.post("/api/calories/course/days/1/open", json={"email": "calories@example.test"}).status_code == 403
        linked = client.get("/api/account/resource-link", params={"target": "calories:calories-stage-01-app"}).json()
        assert linked["action"] == "locked"
        assert linked["reason_code"] == "consultation_required"
        account = client.get("/api/account-auth/account").json()
        card = next(item for item in account["courses"] if item["code"] == "calories")
        assert card["state"] == "consultation_locked"
        assert card["app"] is None
        response = client.put(f"/admin/api/users/{user_id}/course-accesses/ACCESS_CALORIES", json={
            "entitled": True, "start_open": True, "all_lessons_open": False,
        })
        assert response.status_code == 200, response.text
        course = client.get("/api/calories/course", params={"email": "calories@example.test"})
        assert course.status_code == 200, course.text
        assert course.json()["fully_unlocked"] is False
        assert all(not stage["completed_steps"] for stage in course.json()["stages"])
        assert all(not stage["completed"] for stage in course.json()["stages"])
        account = client.get("/api/account-auth/account").json()
        assert next(item for item in account["courses"] if item["code"] == "calories")["app"] == "calories-course"
        first_step = client.get("/api/calories/course/manifest", params={"email": "calories@example.test"}).json()["stages"][0]["steps"][0]["id"]
        assert client.get("/api/account/resource-link", params={"target": f"calories:{first_step}"}).json()["action"] == "open"
    finally:
        client.close()
        factory.kw["bind"].dispose()


def test_recipes_and_masterclass_are_not_delayed_by_consultation():
    client, factory = setup(masterclass_completed=False)
    try:
        with factory() as db:
            user_id, _ = configure(db, resource_code="ACCESS_RECIPES")
            assert course_start_is_open(db, user_id, "ACCESS_RECIPES")
            assert course_entry_unlocked(db, user_id, "ACCESS_RECIPES")
            assert not course_waits_for_consultation(db, user_id, "ACCESS_MASTERCLASS")
    finally:
        client.close()
        factory.kw["bind"].dispose()
