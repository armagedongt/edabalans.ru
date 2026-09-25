import os
import time
import pytest
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")
os.environ.setdefault("APP_AUTH_SECRET", "test-client-session-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.auth import ADMIN_COOKIE, admin_session_token, require_admin  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.account_security import password_hash  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.legal_service import LEGAL_DOCUMENTS  # noqa: E402
from app.main import app  # noqa: E402
import app.main as main_module  # noqa: E402
from app.managed_documents import publish_document  # noqa: E402
from app.models import (  # noqa: E402
    ContentItem,
    ContentItemVersion,
    ContentSource,
    CourseEvent,
    CourseStageProgress,
    CourseStepProgress,
    MasterclassEvent,
    MasterclassNotification,
    MessengerAccount,
    Resource,
    User,
    UserAccess,
    UserEmail,
    UserLegalAcceptance, AccountCredential,
)


def setup(*, course_ready: bool = True, masterclass_completed: bool = True, database_url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        **({"poolclass": StaticPool} if database_url.endswith(":memory:") else {}),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: "test-admin"
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite+pysqlite:///:memory:",
        admin_username="admin@example.test",
        admin_password="test-app-secret",
        app_auth_secret="test-client-session-secret",
    )
    main_module.SessionLocal = factory
    with factory() as db:
        user = User(display_name="Участник Калорийного", status="active")
        denied = User(display_name="Без Калорийного", status="active")
        db.add_all([user, denied])
        db.flush()
        db.add_all(
            [
                UserEmail(
                    user_id=user.id,
                    email_original="calories@example.test",
                    email_normalized="calories@example.test",
                    is_primary=True,
                    source="test",
                ),
                UserEmail(
                    user_id=denied.id,
                    email_original="denied@example.test",
                    email_normalized="denied@example.test",
                    is_primary=True,
                    source="test",
                ),
            ]
        )
        db.add_all([
            AccountCredential(user_id=user.id, password_hash=password_hash("Test-Password-9", "test-client-session-secret"), password_version=1, issued_via="test"),
            AccountCredential(user_id=denied.id, password_hash=password_hash("Test-Password-9", "test-client-session-secret"), password_version=1, issued_via="test"),
        ])
        resource = Resource(
            code="ACCESS_CALORIES", name="Калорийный курс", status="active"
        )
        db.add(resource)
        db.flush()
        db.add(
            UserAccess(
                user_id=user.id,
                resource_id=resource.id,
                source="test",
                granted_at=datetime.now(timezone.utc),
            )
        )
        if masterclass_completed:
            db.add(MasterclassEvent(
                user_id=user.id,
                event_key="masterclass:completed",
                event_type="masterclass_completed",
                details={},
            ))
        for target in (user, denied):
            db.add_all(
                [
                    UserLegalAcceptance(
                        user_id=target.id,
                        document_code=item["code"],
                        document_version=item["version"],
                        source="test",
                    )
                    for item in LEGAL_DOCUMENTS
                ]
            )
        db.commit()
    client = TestClient(app, base_url="https://edabalans.ru")
    if course_ready:
        materials = client.get("/admin/api/courses/calories/materials").json()["materials"]
        for material in materials:
            response = client.put(
                f"/admin/api/courses/calories/materials/{material['step_id']}",
                json={
                    "expected_version": 0,
                    "content": f"## {material['title']}\n\nПроверенный текст материала.",
                    "format": "markdown",
                },
            )
            assert response.status_code == 200
        editor = client.get("/admin/api/courses/calories/structure").json()
        manifest = editor["active"]["manifest"]
        manifest["launchReady"] = True
        manifest["days"] = manifest["stages"]
        response = client.put(
            "/admin/api/courses/calories/structure",
            json={
                "expected_version": editor["active"]["version"],
                "manifest": manifest,
            },
        )
        assert response.status_code == 200
    assert client.post("/api/account-auth/login", json={"email": "calories@example.test", "password": "Test-Password-9"}).status_code == 200
    return client, factory


def teardown_function() -> None:
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.mark.parametrize("block", ["none", "progress", "launched", "version"])
def test_approved_seed_release_is_versioned_and_never_erases_progress(block):
    from app.calorie_course_service import active_course_version
    from app.managed_documents import document_hash
    from scripts.publish_calorie_course_seed import publish_seed

    _, factory = setup(course_ready=False)
    with factory() as db:
        current = active_course_version(db)
        old = deepcopy(current.payload)
        old["courseVersion"] = "previous-structure"
        old["launchReady"] = block == "launched"
        current.payload = old
        current.content_hash = document_hash(old)
        db.commit()
        if block == "progress":
            user_id = db.scalar(select(UserEmail.user_id).where(UserEmail.email_normalized == "calories@example.test"))
            db.add(CourseEvent(user_id=user_id, course_code="calories", event_key="existing", event_type="calories_course_opened"))
            db.commit()
        version = current.version_no
        if block != "none":
            with pytest.raises(ValueError):
                publish_seed(db, expected_version=version + (1 if block == "version" else 0), apply=True)
            assert active_course_version(db).version_no == version
            return
        result = publish_seed(db, expected_version=version, apply=False)
        assert result["applied"] is False
        assert active_course_version(db).payload == old
        result = publish_seed(db, expected_version=version, apply=True)
        assert result["version"] == version + 1
        assert current.payload == old
        assert len(active_course_version(db).payload["stages"]) == 3
        assert not active_course_version(db).payload["launchReady"]
        assert publish_seed(db, expected_version=version+1, apply=True)["changed"] is False


def test_calorie_course_requires_access_and_exposes_three_module_manifest():
    client, factory = setup()
    assert client.post("/api/account-auth/logout").status_code == 200
    assert client.post("/api/account-auth/login", json={"email": "denied@example.test", "password": "Test-Password-9"}).status_code == 200
    denied = client.get("/api/calories/course?email=denied@example.test")
    assert denied.status_code == 403
    assert client.post("/api/account-auth/logout").status_code == 200
    assert client.post("/api/account-auth/login", json={"email": "calories@example.test", "password": "Test-Password-9"}).status_code == 200

    response = client.get("/api/calories/course?email=calories@example.test")
    assert response.status_code == 200
    body = response.json()
    assert len(body["stages"]) == 3
    assert body["stages"][0]["opened"] is True
    assert body["stages"][1]["can_open"] is False

    manifest = client.get(
        "/api/calories/course/manifest?email=calories@example.test"
    ).json()
    assert manifest["courseCode"] == "calories"
    assert len(manifest["stages"]) == 3
    assert manifest["navigation"] == "materials"
    assert [len(stage["steps"]) for stage in manifest["stages"]] == [5, 6, 4]
    assert [len(stage["checks"]) for stage in manifest["stages"]] == [4, 4, 3]
    steps = [step for stage in manifest["stages"] for step in stage["steps"]]
    assert len(steps) == 15
    assert len([step for step in steps if step["kind"] == "article"]) == 15
    assert all(stage["steps"][-1]["assignment"] for stage in manifest["stages"])
    assert all(not stage["steps"][-1]["required"] for stage in manifest["stages"])
    assert all(
        step["contentKind"] == "text"
        for step in steps
        if step["kind"] == "article"
    )

    metabolism = client.get("/api/apps/metabolism?email=calories@example.test")
    assert metabolism.status_code == 200
    assert metabolism.json()["ok"] is True
    saved_metabolism = client.put(
        "/api/apps/metabolism",
        json={
            "email": "calories@example.test",
            "version": metabolism.json()["version"],
            "variants": {"1": {"calories": 2100}},
            "activeVariant": 1,
        },
    )
    assert saved_metabolism.status_code == 200
    assert saved_metabolism.json()["ok"] is True

    admin_users = client.get("/admin/api/apps/users?app_code=metabolism").json()[
        "users"
    ]
    calorie_user = next(
        item for item in admin_users if item["email"] == "calories@example.test"
    )
    assert calorie_user["has_access"] is True
    modules = client.get(
        f"/admin/api/users/{calorie_user['user_id']}/modules"
    ).json()["modules"]
    assert modules["metabolism"]["has_access"] is True
    admin_detail = client.get(
        f"/admin/api/apps/metabolism/users/{calorie_user['user_id']}"
    ).json()
    assert admin_detail["has_access"] is True

    with factory() as db:
        legacy_user = db.scalar(
            select(User).join(UserEmail).where(
                UserEmail.email_normalized == "denied@example.test"
            )
        )
        legacy_resource = Resource(
            code="metabolism", name="Калькулятор метаболизма", status="active"
        )
        db.add(legacy_resource)
        db.flush()
        db.add(
            UserAccess(
                user_id=legacy_user.id,
                resource_id=legacy_resource.id,
                source="test",
                granted_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    assert client.post("/api/account-auth/logout").status_code == 200
    assert client.post("/api/account-auth/login", json={"email": "denied@example.test", "password": "Test-Password-9"}).status_code == 200
    legacy_metabolism = client.get("/api/apps/metabolism")
    assert legacy_metabolism.status_code == 200
    assert legacy_metabolism.json()["ok"] is False
    legacy_saved = client.put(
        "/api/apps/metabolism",
        json={
            "version": 1,
            "variants": {"1": {"calories": 1900}},
            "activeVariant": 1,
        },
    )
    assert legacy_saved.status_code == 400
    assert legacy_saved.json()["ok"] is False


def test_calorie_course_completes_stage_in_order_and_opens_next_at_local_six(monkeypatch):
    import app.calorie_course_routes as routes

    class Clock(datetime):
        instant = datetime(2026, 9, 25, 7, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)

    monkeypatch.setattr(routes, "datetime", Clock)
    client, factory = setup()
    email = "calories@example.test"
    with factory() as db:
        user = db.scalar(select(User).join(UserEmail).where(UserEmail.email_normalized == email))
        db.add(MessengerAccount(user_id=user.id, platform="telegram", platform_user_id="calories-test-user", linked_at=Clock.instant, is_deliverable=True, is_preferred=True, source="test"))
        db.commit()
    opened = client.get(f"/api/calories/course?email={email}&timezone_name=Asia/Yekaterinburg")
    assert opened.json()["stages"][0]["timezone_name"] == "Asia/Yekaterinburg"
    reopened = client.get(f"/api/calories/course?email={email}&timezone_name=Pacific/Kiritimati")
    assert reopened.json()["stages"][0]["timezone_name"] == "Asia/Yekaterinburg"

    early = client.post(
        "/api/calories/course/days/2/open", json={"email": email}
    )
    assert early.status_code == 409
    assert early.json()["detail"]["reason"] == "previous_stage_not_completed"

    out_of_order = client.post("/api/calories/course/days/1/steps/2/complete", json={"email": email})
    assert out_of_order.status_code == 409
    assert client.post("/api/calories/course/days/1/task/open", json={"email": email}).status_code == 409
    assert client.put("/api/calories/course/days/1/checks/0", json={"email": email, "checked": True}).status_code == 409

    for index in range(4):
        completed = client.post(
            f"/api/calories/course/days/1/steps/{index}/complete",
            json={"email": email},
        )
        assert completed.status_code == 200
    opened_task = client.post(
        "/api/calories/course/days/1/task/open", json={"email": email}
    )
    assert opened_task.status_code == 200
    for index in range(4):
        checked = client.put(
            f"/api/calories/course/days/1/checks/{index}",
            json={"email": email, "checked": True},
        )
        assert checked.status_code == 200
        if index < 3:
            assert checked.json()["stages"][0]["completed"] is False
            assert checked.json()["stages"][1]["can_open"] is False
            assert checked.json()["stages"][1]["locked_reason"] == "previous_stage_not_completed"
    assert checked.json()["stages"][0]["completed"] is True
    assert checked.json()["stages"][1]["can_open"] is False
    assert checked.json()["stages"][1]["locked_reason"] == "timer"
    assert checked.json()["stages"][1]["unlock_at"] == "2026-09-26T01:00:00+00:00"
    assert client.get(f"/api/calories/course?email={email}").json()["stages"][0]["checkmarks"] == {str(i): True for i in range(4)}
    Clock.instant = datetime(2026, 9, 26, 0, 59, 59, tzinfo=timezone.utc)
    still_locked = client.post("/api/calories/course/days/2/open", json={"email": email, "timezone_name": "Pacific/Kiritimati"})
    assert still_locked.status_code == 409
    assert still_locked.json()["detail"]["reason"] == "timer"
    Clock.instant = datetime(2026, 9, 26, 1, tzinfo=timezone.utc)

    second = client.post(
        "/api/calories/course/days/2/open", json={"email": email, "timezone_name": "Asia/Yekaterinburg"}
    )
    assert second.status_code == 200
    assert second.json()["stages"][1]["opened"] is True
    assert client.get("/api/apps/metabolism").json()["ok"] is True

    with factory() as db:
        assert db.scalar(select(func.count(MasterclassNotification.id))) == 0

    with factory() as db:
        assert db.scalar(select(func.count(CourseStageProgress.id))) == 2
        assert db.scalar(select(func.count(CourseStepProgress.id))) == 4
        events = set(db.scalars(select(CourseEvent.event_type)))
        assert {
            "calories_course_opened",
            "calories_stage_opened",
            "calories_material_completed",
            "calories_stage_assignment_opened",
            "calories_stage_completed",
        } <= events

    for index in range(5):
        assert client.post(f"/api/calories/course/days/2/steps/{index}/complete", json={"email": email}).status_code == 200
    assert client.post("/api/calories/course/days/2/steps/0/complete", json={"email": email}).status_code == 200
    with factory() as db:
        notification = db.scalars(select(MasterclassNotification).where(MasterclassNotification.notification_kind == "metabolism_app_link")).one()
        assert notification.content_code == "tpl_postpurchase_metabolism_app_link"
        assert notification.payload["target_platform"] == "telegram"
        assert notification.payload["target_platform_user_id"] == "calories-test-user"
        assert db.scalar(select(func.count(MasterclassEvent.id)).where(MasterclassEvent.event_type == "app_revealed_metabolism")) == 1
    assert client.post("/api/calories/course/days/2/task/open", json={"email": email}).status_code == 200
    for index in range(4):
        assert client.put(f"/api/calories/course/days/2/checks/{index}", json={"email": email, "checked": True}).status_code == 200
    assert client.get("/api/apps/metabolism").json()["ok"] is True
    application = next(row for row in client.get("/api/account-auth/account").json()["applications"] if row["code"] == "metabolism")
    assert application["app"] == "metabolism"
    Clock.instant = datetime(2026, 9, 27, 1, tzinfo=timezone.utc)
    assert client.post("/api/calories/course/days/3/open", json={"email": email}).status_code == 200
    for index in range(3):
        assert client.post(f"/api/calories/course/days/3/steps/{index}/complete", json={"email": email}).status_code == 200
    assert client.post("/api/calories/course/days/3/task/open", json={"email": email}).status_code == 200
    for index in range(3):
        finished = client.put(f"/api/calories/course/days/3/checks/{index}", json={"email": email, "checked": True})
        assert finished.status_code == 200
    assert all(stage["completed"] for stage in finished.json()["stages"])
    with factory() as db:
        assert db.scalar(select(func.count(CourseEvent.id)).where(CourseEvent.event_type == "calories_course_completed")) == 1


def test_calorie_course_and_calculator_are_blocked_until_masterclass_completion(monkeypatch):
    client, _ = setup(masterclass_completed=False)
    course = client.get("/api/calories/course?email=calories@example.test")
    assert course.status_code == 403
    assert "после завершения Мастер-класса" in course.json()["detail"]
    calculator = client.get("/api/apps/metabolism")
    assert calculator.status_code == 200
    assert calculator.json()["ok"] is False
    from app.product_catalog_service import PRODUCT_CONNECTIONS
    monkeypatch.setitem(PRODUCT_CONNECTIONS["calories"], "maintenance", False)
    account = client.get("/api/account-auth/account").json()
    calories = next(item for item in account["courses"] if item["code"] == "calories")
    assert calories["state"] == "masterclass_locked"
    assert calories["app"] is None
    linked = client.get(
        "/api/account/resource-link",
        params={"target": "calories:calories-stage-01-app"},
    )
    assert linked.status_code == 200
    assert linked.json()["action"] == "locked"
    assert linked.json()["reason_code"] == "masterclass_not_completed"


def test_manual_full_unlock_bypasses_course_prerequisite_and_internal_sequence():
    client, factory = setup(masterclass_completed=False)
    with factory() as db:
        user_id = db.scalar(
            select(UserEmail.user_id).where(
                UserEmail.email_normalized == "calories@example.test"
            )
        )

    policy = client.put(
        f"/admin/api/users/{user_id}/course-policies/ACCESS_CALORIES",
        json={"unlock_mode": "fully_unlocked"},
    )
    assert policy.status_code == 200

    course = client.get("/api/calories/course?email=calories@example.test")
    assert course.status_code == 200
    assert course.json()["fully_unlocked"] is True
    assert all(stage["can_open"] for stage in course.json()["stages"])

    opened = client.post(
        "/api/calories/course/days/3/open",
        json={"email": "calories@example.test"},
    )
    assert opened.status_code == 200
    completed = client.post(
        "/api/calories/course/days/3/steps/2/complete",
        json={"email": "calories@example.test"},
    )
    assert completed.status_code == 200
    task = client.post(
        "/api/calories/course/days/3/task/open",
        json={"email": "calories@example.test"},
    )
    assert task.status_code == 200

    linked = client.get(
        "/api/account/resource-link",
        params={"target": "calories:calories-actions"},
    )
    assert linked.status_code == 200
    assert linked.json()["action"] == "open"
    assert linked.json()["params"]["calories_stage"] == 3


def test_resource_link_discovers_newly_published_material_from_active_structure():
    client, factory = setup()
    editor = client.get("/admin/api/courses/calories/structure").json()
    manifest = editor["active"]["manifest"]
    new_step = dict(manifest["stages"][0]["steps"][0])
    new_step.update(
        {
            "id": "calories-stage-01-new-material",
            "title": "Новый материал",
            "summary": "Добавлен через редактор структуры.",
        }
    )
    manifest["stages"][0]["steps"].insert(0, new_step)
    manifest["days"] = manifest["stages"]
    with factory() as db:
        publish_document(
            db,
            document_type="course-structure",
            document_key="calories",
            schema_version=1,
            payload=manifest,
            expected_version=editor["active"]["version"],
            admin="test-chat-release",
        )
    published = client.put(
        "/admin/api/courses/calories/materials/calories-stage-01-new-material",
        json={
            "expected_version": 0,
            "content": "## Новый материал\n\nТекст из редактора.",
            "format": "markdown",
        },
    )
    assert published.status_code == 200

    linked = client.get(
        "/api/account/resource-link",
        params={"target": "calories:calories-stage-01-new-material"},
    )
    assert linked.status_code == 200
    assert linked.json()["action"] == "open"
    assert linked.json()["params"] == {
        "calories_stage": 1,
        "calories_material": "calories-stage-01-new-material",
    }


def test_calorie_material_can_be_published_without_structure_deploy():
    client, factory = setup(course_ready=False)
    step_id = "calories-stage-01-app"
    initial = client.get(f"/admin/api/courses/calories/materials/{step_id}")
    assert initial.status_code == 200
    assert initial.json()["version"] == 0

    published = client.put(
        f"/admin/api/courses/calories/materials/{step_id}",
        json={
            "expected_version": 0,
            "content": "## Проверяем приложение\n\nПолный рабочий текст.",
            "format": "markdown",
        },
    )
    assert published.status_code == 200
    assert published.json()["version"] == 1
    assert "<h2>Проверяем приложение</h2>" in published.json()["html"]

    runtime = client.get(
        "/api/calories/course/materials?email=calories@example.test"
    )
    assert runtime.status_code == 409
    assert runtime.json()["detail"]["reason"] == "course_preparing"
    with factory() as db:
        source = db.scalar(
            select(ContentSource).where(
                ContentSource.account_key == "calories-course-materials"
            )
        )
        assert source is not None
        assert db.scalar(select(func.count(ContentItem.id))) == 1
        assert db.scalar(select(func.count(ContentItemVersion.id))) == 1


def test_course_editor_lists_calories_and_updates_stage_copy():
    client, _ = setup(course_ready=False)
    admin_settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        admin_username="admin@example.test",
        admin_password="test-app-secret",
    )
    with patch("app.auth.get_settings", return_value=admin_settings):
        client.cookies.set(
            ADMIN_COOKIE,
            admin_session_token("admin@example.test", int(time.time()) + 60),
        )
        editor_page = client.get("/admin/courses/calories/structure")
    assert editor_page.status_code == 200
    assert 'id="course-heading"' in editor_page.text
    courses = client.get("/admin/api/courses")
    assert courses.status_code == 200
    assert {item["code"] for item in courses.json()["courses"]} == {
        "masterclass-21",
        "calories",
    }
    calorie_card = next(
        item for item in courses.json()["courses"] if item["code"] == "calories"
    )
    assert calorie_card["materials_total"] == 15
    assert calorie_card["materials_published"] == 0
    assert calorie_card["launch_ready"] is False
    assert calorie_card["ready"] is False

    editor = client.get("/admin/api/courses/calories/structure").json()
    assert editor["course"]["unit_name"] == "этап"
    manifest = editor["active"]["manifest"]
    manifest["stages"][0]["lead"] = "Обновлённая рабочая подводка."
    manifest["days"] = manifest["stages"]
    saved = client.put(
        "/admin/api/courses/calories/structure",
        json={
            "expected_version": editor["active"]["version"],
            "manifest": manifest,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["active"]["manifest"]["stages"][0]["lead"] == "Обновлённая рабочая подводка."


def test_calorie_course_stays_closed_until_every_material_and_launch_switch_are_ready(monkeypatch):
    from app.product_catalog_service import PRODUCT_CONNECTIONS

    monkeypatch.setitem(PRODUCT_CONNECTIONS["calories"], "maintenance", False)
    client, _ = setup(course_ready=False)
    email = "calories@example.test"

    account = client.get(f"/api/account?email={email}").json()
    calorie_card = next(item for item in account["courses"] if item["code"] == "calories")
    assert calorie_card["owned"] is True
    assert calorie_card["ready"] is False
    assert calorie_card["state"] == "preparing"
    assert calorie_card["app"] is None
    direct = client.get(f"/api/calories/course/manifest?email={email}")
    assert direct.status_code == 409
    assert direct.json()["detail"]["reason"] == "course_preparing"

    materials = client.get("/admin/api/courses/calories/materials").json()["materials"]
    assert len(materials) == 15
    for material in materials:
        published = client.put(
            f"/admin/api/courses/calories/materials/{material['step_id']}",
            json={
                "expected_version": 0,
                "content": f"## {material['title']}\n\nПроверенный текст материала.",
                "format": "markdown",
            },
        )
        assert published.status_code == 200

    account = client.get(f"/api/account?email={email}").json()
    calorie_card = next(item for item in account["courses"] if item["code"] == "calories")
    assert calorie_card["ready"] is False

    editor = client.get("/admin/api/courses/calories/structure").json()
    manifest = editor["active"]["manifest"]
    manifest["launchReady"] = True
    manifest["days"] = manifest["stages"]
    saved = client.put(
        "/admin/api/courses/calories/structure",
        json={"expected_version": editor["active"]["version"], "manifest": manifest},
    )
    assert saved.status_code == 200

    account = client.get(f"/api/account?email={email}").json()
    calorie_card = next(item for item in account["courses"] if item["code"] == "calories")
    assert calorie_card["ready"] is True
    assert calorie_card["state"] == "available"
    assert calorie_card["app"] == "calories-course"
    assert client.get(f"/api/calories/course/manifest?email={email}").status_code == 200

    runtime_materials = client.get(f"/api/calories/course/materials?email={email}")
    assert runtime_materials.status_code == 200
    assert len(runtime_materials.json()["materials"]) == 5
    assert all(
        item["html"].startswith("<h2>")
        for item in runtime_materials.json()["materials"].values()
    )


def test_launch_switch_cannot_open_course_with_missing_materials():
    client, _ = setup(course_ready=False)
    email = "calories@example.test"

    first = client.get("/admin/api/courses/calories/materials").json()["materials"][0]
    published = client.put(
        f"/admin/api/courses/calories/materials/{first['step_id']}",
        json={
            "expected_version": 0,
            "content": "## Первый материал\n\nОстальные материалы ещё не готовы.",
            "format": "markdown",
        },
    )
    assert published.status_code == 200

    editor = client.get("/admin/api/courses/calories/structure").json()
    manifest = editor["active"]["manifest"]
    manifest["launchReady"] = True
    manifest["days"] = manifest["stages"]
    saved = client.put(
        "/admin/api/courses/calories/structure",
        json={"expected_version": editor["active"]["version"], "manifest": manifest},
    )
    assert saved.status_code == 200

    account = client.get(f"/api/account?email={email}").json()
    calorie_card = next(item for item in account["courses"] if item["code"] == "calories")
    assert calorie_card["ready"] is False
    admin_card = next(
        item
        for item in client.get("/admin/api/courses").json()["courses"]
        if item["code"] == "calories"
    )
    assert admin_card["materials_published"] == 1
    assert admin_card["launch_ready"] is True
    assert admin_card["ready"] is False
    assert client.get(f"/api/calories/course/manifest?email={email}").status_code == 409


def test_material_filter_does_not_expose_locked_modules_or_hidden_articles():
    client, _ = setup()
    endpoint = "/api/calories/course/materials"
    params = {"email": "calories@example.test", "step_id": "calories-stage-01-app"}
    assert set(client.get(endpoint, params=params).json()["materials"]) == {params["step_id"]}
    for unavailable in ("calories-stage-03-expenditure", "calories-whats-next", "unknown"):
        assert client.get(endpoint, params={**params, "step_id": unavailable}).json()["materials"] == {}
    editor = client.get("/admin/api/courses/calories/structure").json()
    manifest = editor["active"]["manifest"]
    manifest["stages"][0]["steps"][1]["hidden"] = True
    manifest["days"] = manifest["stages"]
    assert client.put("/admin/api/courses/calories/structure", json={"expected_version": editor["active"]["version"], "manifest": manifest}).status_code == 200
    assert client.get(endpoint, params=params).json()["materials"] == {}


def test_hidden_article_does_not_block_launch_when_visible_articles_are_published():
    client, _ = setup(course_ready=False)
    email = "calories@example.test"
    editor = client.get("/admin/api/courses/calories/structure").json()
    manifest = editor["active"]["manifest"]
    hidden_step_id = manifest["stages"][0]["steps"][0]["id"]
    manifest["stages"][0]["steps"][0]["hidden"] = True
    manifest["launchReady"] = True
    manifest["days"] = manifest["stages"]
    saved = client.put(
        "/admin/api/courses/calories/structure",
        json={"expected_version": editor["active"]["version"], "manifest": manifest},
    )
    assert saved.status_code == 200

    materials = client.get("/admin/api/courses/calories/materials").json()["materials"]
    for material in materials:
        if material["step_id"] == hidden_step_id:
            continue
        published = client.put(
            f"/admin/api/courses/calories/materials/{material['step_id']}",
            json={
                "expected_version": 0,
                "content": f"## {material['title']}\n\nПроверенный текст материала.",
                "format": "markdown",
            },
        )
        assert published.status_code == 200

    admin_card = next(
        item
        for item in client.get("/admin/api/courses").json()["courses"]
        if item["code"] == "calories"
    )
    assert admin_card["materials_total"] == 14
    assert admin_card["materials_published"] == 14
    assert admin_card["ready"] is True
    assert client.get(f"/api/calories/course/manifest?email={email}").status_code == 200


def test_calorie_course_reuses_masterclass_shell_with_stage_routes(monkeypatch):
    from app.product_catalog_service import PRODUCT_CONNECTIONS

    monkeypatch.setitem(PRODUCT_CONNECTIONS["calories"], "maintenance", False)
    client, _ = setup(course_ready=False)
    fragment = client.get("/apps/calories-course.html")
    assert fragment.status_code == 200
    assert 'id="calories-course-app"' in fragment.text
    assert "/api/calories/course" in fragment.text
    assert "calories_stage" in fragment.text
    assert "Этап " in fragment.text
    assert "Калорийный курс завершён" in fragment.text
    assert "edabalans:calories-event" in fragment.text
    assert "edabalans:masterclass-event" not in fragment.text
    assert "Следующий этап откроется сразу после выполнения задания." not in fragment.text
    assert "#calories-course-app .timer{display:none}" not in fragment.text
    assert "06:00" in fragment.text
    assert "/assets/calories-course.css" in fragment.text
    assert "renderMaterialMenu" in fragment.text
    assert "через этап" not in fragment.text

    account = client.get("/apps/account.html").text
    assert "calories_stage" in account
    assert "calories-course" in account
