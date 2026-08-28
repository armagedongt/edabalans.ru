import os
import time
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.auth import ADMIN_COOKIE, admin_session_token, require_admin  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.legal_service import LEGAL_DOCUMENTS  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    ContentItem,
    ContentItemVersion,
    ContentSource,
    CourseEvent,
    CourseStageProgress,
    CourseStepProgress,
    Resource,
    User,
    UserAccess,
    UserEmail,
    UserLegalAcceptance,
)


def setup(*, course_ready: bool = True):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
    )
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
    client = TestClient(app)
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
    return client, factory


def teardown_function() -> None:
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_calorie_course_requires_access_and_exposes_five_stage_manifest():
    client, factory = setup()
    denied = client.get("/api/calories/course?email=denied@example.test")
    assert denied.status_code == 403

    response = client.get("/api/calories/course?email=calories@example.test")
    assert response.status_code == 200
    body = response.json()
    assert len(body["stages"]) == 5
    assert body["stages"][0]["opened"] is True
    assert body["stages"][1]["can_open"] is False

    manifest = client.get(
        "/api/calories/course/manifest?email=calories@example.test"
    ).json()
    assert manifest["courseCode"] == "calories"
    assert len(manifest["stages"]) == 5
    steps = [step for stage in manifest["stages"] for step in stage["steps"]]
    assert len(steps) == 15
    assert len([step for step in steps if step["kind"] == "article"]) == 14
    calculator = next(step for step in steps if step["id"] == "calories-stage-03-calculator")
    assert calculator["kind"] == "metabolism"
    assert calculator["code"] == "metabolism"
    assert all(
        step["contentKind"] == "placeholder"
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

    legacy_metabolism = client.get(
        "/api/apps/metabolism?email=denied@example.test"
    )
    assert legacy_metabolism.status_code == 200
    assert legacy_metabolism.json()["ok"] is True
    legacy_saved = client.put(
        "/api/apps/metabolism",
        json={
            "email": "denied@example.test",
            "version": legacy_metabolism.json()["version"],
            "variants": {"1": {"calories": 1900}},
            "activeVariant": 1,
        },
    )
    assert legacy_saved.status_code == 200
    assert legacy_saved.json()["ok"] is True


def test_calorie_course_completes_stage_in_order_and_opens_next_immediately():
    client, factory = setup()
    email = "calories@example.test"
    client.get(f"/api/calories/course?email={email}")

    early = client.post(
        "/api/calories/course/days/2/open", json={"email": email}
    )
    assert early.status_code == 409
    assert early.json()["detail"]["reason"] == "previous_stage_not_completed"

    for index in range(3):
        completed = client.post(
            f"/api/calories/course/days/1/steps/{index}/complete",
            json={"email": email},
        )
        assert completed.status_code == 200
    opened_task = client.post(
        "/api/calories/course/days/1/task/open", json={"email": email}
    )
    assert opened_task.status_code == 200
    for index in range(3):
        checked = client.put(
            f"/api/calories/course/days/1/checks/{index}",
            json={"email": email, "checked": True},
        )
        assert checked.status_code == 200
    assert checked.json()["stages"][0]["completed"] is True
    assert checked.json()["stages"][1]["can_open"] is True

    second = client.post(
        "/api/calories/course/days/2/open", json={"email": email}
    )
    assert second.status_code == 200
    assert second.json()["stages"][1]["opened"] is True

    with factory() as db:
        assert db.scalar(select(func.count(CourseStageProgress.id))) == 2
        assert db.scalar(select(func.count(CourseStepProgress.id))) == 3
        events = set(db.scalars(select(CourseEvent.event_type)))
        assert {
            "calories_course_opened",
            "calories_stage_opened",
            "calories_material_completed",
            "calories_stage_assignment_opened",
            "calories_stage_completed",
        } <= events


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
    assert calorie_card["materials_total"] == 14
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


def test_calorie_course_stays_closed_until_every_material_and_launch_switch_are_ready():
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
    assert len(materials) == 14
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
    assert len(runtime_materials.json()["materials"]) == 3
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
    assert admin_card["materials_total"] == 13
    assert admin_card["materials_published"] == 13
    assert admin_card["ready"] is True
    assert client.get(f"/api/calories/course/manifest?email={email}").status_code == 200


def test_calorie_course_reuses_masterclass_shell_with_stage_routes():
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
    assert "Следующий этап откроется сразу после выполнения задания." in fragment.text
    assert "окончания таймера" not in fragment.text
    assert "#calories-course-app .timer{display:none}" in fragment.text
    assert "Следующий этап откроется сразу" in fragment.text
    assert "через этап" not in fragment.text

    account = client.get("/apps/account.html").text
    assert "calories_stage" in account
    assert "calories-course" in account
