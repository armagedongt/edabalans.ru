from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.cookies import SimpleCookie

from test_intensive_web_access import make_client, create_user

from fastapi import Response

from app.account_auth_routes import COOKIE_NAME, set_native_session
from app.config import get_settings
from app.intensive_web_access import issue_access_token
from app.main import app
from app.models import AccountCredential, ReadingPosition, Resource, UserAccess, UserCoursePolicy, UserEmail


def test_reading_position_is_private_expires_and_rejects_stale_writes():
    client, factory = make_client()
    url = "/api/account/reading-position?target=intensive:onepage"
    position = {"index": 3, "fingerprint": "1x4"}
    try:
        assert client.get(url).status_code == 401
        first = create_user(factory)
        second = create_user(factory)
        with factory() as db:
            first_token, _ = issue_access_token(db, first.id, "telegram")
            second_token, _ = issue_access_token(db, second.id, "max")
            db.commit()

        assert client.get(f"/intensive?i={first_token}").status_code == 200
        client.headers["X-Reading-Account"] = sha256(first.id.bytes).hexdigest()
        assert client.get(url).json()["version"] == 0
        saved = client.put(url, json={"version": 0, "position": position})
        assert saved.status_code == 200
        assert saved.json()["version"] == 1
        assert client.put(url, json={"version": 0, "position": position}).status_code == 409

        client.cookies.clear()
        assert client.get(f"/intensive?i={second_token}").status_code == 200
        assert client.get(url).status_code == 409
        client.headers["X-Reading-Account"] = sha256(second.id.bytes).hexdigest()
        assert client.get(url).json()["position"] is None

        client.cookies.clear()
        assert client.get(f"/intensive?i={first_token}").status_code == 200
        client.headers["X-Reading-Account"] = sha256(first.id.bytes).hexdigest()
        assert client.get(url).json()["position"] == position
        with factory() as db:
            row = db.get(ReadingPosition, (first.id, "intensive:onepage"))
            row.saved_at = datetime.now(timezone.utc) - timedelta(days=4)
            db.commit()
        assert client.get(url).json()["position"] is None

        assert client.put(url, json={"version": 1, "position": None}).status_code == 200
        assert client.put(url, json={"version": 1, "position": position}).status_code == 409
        assert client.get(url).json()["position"] is None
    finally:
        app.dependency_overrides.clear()

def test_native_reader_can_save_only_accessible_course_material():
    client, factory = make_client()
    try:
        user = create_user(factory)
        email = "course-reader@example.test"
        with factory() as db:
            db.add(UserEmail(user_id=user.id, email_original=email, email_normalized=email, is_primary=True, source="test"))
            db.add(AccountCredential(user_id=user.id, password_hash="fixture", issued_via="test"))
            db.commit()
            settings = app.dependency_overrides[get_settings]()
            session_response = Response()
            set_native_session(session_response, db, user, settings)

        client.cookies.set(COOKIE_NAME, SimpleCookie(session_response.headers["set-cookie"])[COOKIE_NAME].value)
        headers = {"X-Reading-Account": email}
        url = "/api/account/reading-position?target=masterclass-21:day-01-article-02"
        assert client.get(url, headers=headers).status_code == 404
        assert client.put(url, headers=headers, json={"version": 0, "position": None}).status_code == 404

        with factory() as db:
            course = Resource(code="ACCESS_MASTERCLASS", name="Course fixture", status="active")
            db.add(course)
            db.flush()
            db.add(UserAccess(user_id=user.id, resource_id=course.id, source="test",
                              granted_at=datetime.now(timezone.utc)))
            db.add(UserCoursePolicy(user_id=user.id, resource_id=course.id, source="test",
                                    start_mode="open", unlock_mode="fully_unlocked"))
            db.commit()

        position = {"index": 1, "fingerprint": "1p"}
        response = client.put(url, headers=headers, json={"version": 0, "position": position})
        assert response.status_code == 200, response.text
        assert client.get(url, headers=headers).json()["position"] == position
    finally:
        app.dependency_overrides.clear()
