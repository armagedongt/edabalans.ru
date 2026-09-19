import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.app_routes import BASE_STRENGTH_EXERCISES  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.importers.google_apps import import_strength  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AdminAppEdit,
    DqsState,
    MetabolismState,
    Resource,
    StrengthState,
    User,
    UserAccess,
    UserEmail,
)


get_settings.cache_clear()


def make_client():
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
    client = TestClient(app, base_url="https://app.edabalans.ru")
    return client, factory


def add_user(db, email, name):
    user = User(display_name=name, status="active")
    db.add(user)
    db.flush()
    db.add(UserEmail(
        user_id=user.id,
        email_original=email,
        email_normalized=email,
        is_primary=True,
        source="test",
    ))
    return user


def login(client):
    response = client.post("/admin/api/login", json={
        "username": "admin@example.com",
        "password": "test-admin-password",
    })
    assert response.status_code == 200


def test_admin_app_list_includes_access_without_state_and_state_without_access():
    client, factory = make_client()
    with factory() as db:
        resource = Resource(code="dqs", name="DQS", status="active")
        access_only = add_user(db, "access@example.test", "Есть доступ")
        state_only = add_user(db, "state@example.test", "Есть история")
        search_only = add_user(db, "search@example.test", "Только поиск")
        db.add(UserEmail(
            user_id=search_only.id,
            email_original="legacy-search@example.test",
            email_normalized="legacy-search@example.test",
            is_primary=False,
            source="test",
        ))
        db.add(resource)
        db.flush()
        db.add(UserAccess(
            user_id=access_only.id,
            resource_id=resource.id,
            source="test",
            granted_at=datetime.now(timezone.utc),
        ))
        db.add(DqsState(user_id=state_only.id, days={"1": {"p": [0] * 17, "d": [None] * 17}}))
        db.commit()
        access_id = access_only.id
        search_id = search_only.id

    login(client)
    response = client.get("/admin/api/apps/users?app_code=dqs")
    assert response.status_code == 200
    rows = {row["email"]: row for row in response.json()["users"]}
    assert rows["access@example.test"]["has_access"] is True
    assert rows["access@example.test"]["has_state"] is False
    assert rows["state@example.test"]["has_access"] is False
    assert rows["state@example.test"]["has_state"] is True
    assert "search@example.test" not in rows
    assert response.json()["users"][0]["email"] == "state@example.test"

    searched = client.get(
        "/admin/api/apps/users",
        params={"app_code": "dqs", "q": "legacy-search@example"},
    )
    assert searched.status_code == 200
    assert searched.json()["users"] == [{
        "user_id": str(search_id),
        "display_name": "Только поиск",
        "email": "search@example.test",
        "has_access": False,
        "has_state": False,
        "version": None,
        "updated_at": "",
        "summary": {},
    }]

    detail = client.get(f"/admin/api/apps/dqs/users/{access_id}").json()
    assert detail["has_access"] is True
    assert detail["has_state"] is False
    assert detail["state"] is None

    opened = client.post(f"/admin/api/apps/dqs/users/{access_id}/open")
    assert opened.status_code == 200
    assert opened.json()["created"] is True
    with factory() as db:
        assert db.scalar(select(func.count(DqsState.id))) == 2
        edit = db.scalar(select(AdminAppEdit).where(AdminAppEdit.target_user_id == access_id))
        assert edit.action == "open_empty_state"


def test_admin_can_open_metabolism_with_calories_course_access():
    client, factory = make_client()
    with factory() as db:
        resource = Resource(code="ACCESS_CALORIES", name="Курс о калориях", status="active")
        user = add_user(db, "calories@example.test", "Участник курса")
        db.add(resource)
        db.flush()
        db.add(UserAccess(
            user_id=user.id,
            resource_id=resource.id,
            source="test",
            granted_at=datetime.now(timezone.utc),
        ))
        db.commit()
        user_id = user.id

    login(client)
    detail = client.get(f"/admin/api/apps/metabolism/users/{user_id}")
    assert detail.status_code == 200
    assert detail.json()["has_access"] is True
    assert detail.json()["has_state"] is False

    opened = client.post(f"/admin/api/apps/metabolism/users/{user_id}/open")
    assert opened.status_code == 200
    assert opened.json()["created"] is True
    with factory() as db:
        edit = db.scalar(select(AdminAppEdit).where(AdminAppEdit.target_user_id == user_id))
        assert edit.app_code == "metabolism"
        assert edit.action == "open_empty_state"


def test_admin_cannot_open_app_with_inactive_resource():
    client, factory = make_client()
    with factory() as db:
        resource = Resource(code="dqs", name="DQS", status="inactive")
        user = add_user(db, "inactive@example.test", "Отключённый доступ")
        db.add(resource)
        db.flush()
        db.add(UserAccess(
            user_id=user.id,
            resource_id=resource.id,
            source="test",
            granted_at=datetime.now(timezone.utc),
        ))
        db.commit()
        user_id = user.id

    login(client)
    detail = client.get(f"/admin/api/apps/dqs/users/{user_id}")
    assert detail.status_code == 200
    assert detail.json()["has_access"] is False

    opened = client.post(f"/admin/api/apps/dqs/users/{user_id}/open")
    assert opened.status_code == 403
    with factory() as db:
        assert db.scalar(select(DqsState).where(DqsState.user_id == user_id)) is None


def test_strength_admin_mobile_list_requires_admin_and_returns_only_profiles_with_records():
    client, factory = make_client()
    with factory() as db:
        with_history = add_user(db, "history@example.test", "Есть тренировки")
        empty_state = add_user(db, "empty@example.test", "Только открыл")
        db.add(StrengthState(
            user_id=with_history.id,
            workout_types=[],
            hidden_exercises=[],
            workouts=[{"session_id": "one", "workout_type": 1, "date": "2026-09-10"}],
        ))
        db.add(StrengthState(
            user_id=empty_state.id,
            workout_types=[],
            hidden_exercises=[],
            workouts=[],
        ))
        db.commit()

    denied = client.get(
        "/admin/api/apps/users",
        params={"app_code": "strength", "with_records": True},
    )
    assert denied.status_code == 401

    login(client)
    response = client.get(
        "/admin/api/apps/users",
        params={"app_code": "strength", "with_records": True},
    )
    assert response.status_code == 200
    assert [row["email"] for row in response.json()["users"]] == ["history@example.test"]

    response = client.get(
        "/admin/api/apps/users",
        params={"app_code": "strength", "with_records": True, "q": "HISTORY@EXAMPLE"},
    )
    assert response.status_code == 200
    rows = response.json()["users"]
    assert [row["email"] for row in rows] == ["history@example.test"]
    assert rows[0]["summary"]["sessions"] == 1


def test_strength_managed_runtime_uses_admin_session_and_writes_audit():
    client, factory = make_client()
    with factory() as db:
        user = add_user(db, "strength@example.test", "Тренирующийся")
        db.add(StrengthState(
            user_id=user.id,
            workout_types=[],
            hidden_exercises=[],
            workouts=[],
        ))
        db.commit()
        user_id = user.id

    login(client)
    opened = client.get(f"/api/apps/strength?action=openUser&target_user_id={user_id}")
    assert opened.status_code == 200
    assert opened.json()["user"]["user_id"] == str(user_id)

    saved = client.post("/api/apps/strength", content=(
        '{"action":"saveExerciseSettings","target_user_id":"%s",'
        '"workout_type":1,"version":1,"exercises":[]}' % user_id
    ))
    assert saved.status_code == 200
    assert saved.json()["ok"] is True
    with factory() as db:
        edit = db.scalar(select(AdminAppEdit).where(AdminAppEdit.target_user_id == user_id))
        assert edit.app_code == "strength"
        assert edit.action == "saveExerciseSettings"


def test_strength_completed_set_round_trips_for_the_selected_user():
    client, factory = make_client()
    with factory() as db:
        user = add_user(db, "strength-completed@example.test", "Тренирующийся")
        db.add(StrengthState(
            user_id=user.id,
            workout_types=[],
            hidden_exercises=[],
            workouts=[],
        ))
        db.commit()
        user_id = user.id

    login(client)
    saved = client.post(
        "/api/apps/strength",
        json={
            "action": "saveSession",
            "target_user_id": str(user_id),
            "workout_type": 1,
            "version": 1,
            "session": {
                "session_number": 1,
                "date": "2026-09-09",
                "exercises": [{
                    "exercise_id": "bench_press",
                    "exercise_name": "Жим лёжа",
                    "sets": [{
                        "set_number": 1,
                        "plan_weight": "40",
                        "plan_reps": "10",
                        "fact_weight": "40",
                        "fact_reps": "10",
                        "rpe": "8",
                        "completed": True,
                    }],
                }],
            },
        },
    )
    assert saved.status_code == 200
    assert saved.json()["ok"] is True

    loaded = client.get(
        "/api/apps/strength",
        params={"action": "getWorkout", "target_user_id": str(user_id), "type": 1},
    )
    assert loaded.status_code == 200
    assert loaded.json()["workout"]["sets"][0]["completed"] is True


def test_strength_server_assigns_globally_unique_numbers_and_ids():
    client, factory = make_client()
    with factory() as db:
        user = add_user(db, "strength-numbering@example.test", "Нумерация")
        db.add(StrengthState(
            user_id=user.id,
            workout_types=[],
            hidden_exercises=[],
            workouts=[],
        ))
        db.commit()
        user_id = user.id

    login(client)

    version = 1

    def create(workout_type: int) -> dict:
        nonlocal version
        response = client.post(
            "/api/apps/strength",
            json={
                "action": "saveSession",
                "target_user_id": str(user_id),
                "workout_type": workout_type,
                "version": version,
                "session": {"session_number": 99, "date": "2026-09-10", "exercises": []},
            },
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        version = response.json()["version"]
        return response.json()["session"]

    first = create(1)
    second = create(1)
    other_template = create(2)

    assert first["session_number"] == 1
    assert second["session_number"] == 2
    assert other_template["session_number"] == 3
    assert uuid.UUID(first["session_id"])
    assert uuid.UUID(second["session_id"])
    assert uuid.UUID(other_template["session_id"])
    assert first["session_id"] != second["session_id"]
    assert other_template["session_id"] not in {first["session_id"], second["session_id"]}


def test_strength_payload_and_stats_include_exercise_history_from_every_template():
    client, factory = make_client()
    with factory() as db:
        user = add_user(db, "strength-global-history@example.test", "История")
        db.add(StrengthState(
            user_id=user.id,
            workout_types=[],
            hidden_exercises=[],
            workouts=[
                {
                    "session_id": "t1-1", "workout_type": 1, "session_number": 1,
                    "date": "2026-09-01", "exercises": [{
                        "exercise_id": "romanian-deadlift", "exercise_name": "Румынская тяга", "sets": [
                            {"set_number": 1, "fact_weight": "50", "fact_reps": "8", "rpe": "8"},
                            {"set_number": 2, "fact_weight": "50", "fact_reps": "8", "rpe": "8"},
                        ],
                    }],
                },
                {
                    "session_id": "t3-2", "workout_type": 3, "session_number": 2,
                    "date": "2026-09-03", "exercises": [{
                        "exercise_id": "romanian-deadlift", "exercise_name": "Румынская тяга", "sets": [
                            {"set_number": 1, "fact_weight": "55", "fact_reps": "8", "rpe": "8"},
                            {"set_number": 2, "fact_weight": "55", "fact_reps": "8", "rpe": "8"},
                        ],
                    }],
                },
            ],
        ))
        db.commit()
        user_id = user.id

    login(client)
    workout = client.get(
        "/api/apps/strength",
        params={"action": "getWorkout", "target_user_id": str(user_id), "type": 3},
    ).json()["workout"]
    assert [item["session_number"] for item in workout["sessions"]] == [1, 2]
    assert [item["workout_type"] for item in workout["sessions"]] == [1, 3]

    stats = client.get(
        "/api/apps/strength",
        params={
            "action": "getStats", "target_user_id": str(user_id), "type": 3,
            "exercise_id": "romanian-deadlift",
        },
    ).json()["stats"]
    assert [item["session_number"] for item in stats] == [1, 2]


def test_strength_rejects_stale_state_version_without_overwriting_session():
    client, factory = make_client()
    with factory() as db:
        user = add_user(db, "strength-version@example.test", "Версия")
        db.add(StrengthState(user_id=user.id, workout_types=[], hidden_exercises=[], workouts=[]))
        db.commit()
        user_id = user.id

    login(client)
    first = client.post("/api/apps/strength", json={
        "action": "saveSession", "target_user_id": str(user_id), "workout_type": 1,
        "version": 1, "session": {"date": "2026-09-10", "exercises": []},
    }).json()
    assert first["ok"] is True
    stale = client.post("/api/apps/strength", json={
        "action": "saveSession", "target_user_id": str(user_id), "workout_type": 2,
        "version": 1, "session": {"date": "2026-09-11", "exercises": []},
    }).json()
    assert stale == {"ok": False, "error": "STRENGTH_STATE_CONFLICT"}
    with factory() as db:
        state = db.scalar(select(StrengthState).where(StrengthState.user_id == user_id))
        assert [workout["session_number"] for workout in state.workouts] == [1]


def test_strength_undo_can_delete_a_newly_created_session():
    client, factory = make_client()
    with factory() as db:
        user = add_user(db, "strength-delete@example.test", "Отмена")
        db.add(StrengthState(user_id=user.id, workout_types=[], hidden_exercises=[], workouts=[]))
        db.commit()
        user_id = user.id

    login(client)
    session_id = "browser-created-session"
    created = client.post("/api/apps/strength", json={
        "action": "saveSession", "target_user_id": str(user_id), "workout_type": 1,
        "version": 1, "session": {"session_id": session_id, "session_number": 99, "date": "2026-09-10", "exercises": []},
    }).json()
    assert created["ok"] is True
    assert created["session"]["session_number"] == 1
    deleted = client.post("/api/apps/strength", json={
        "action": "saveSession", "target_user_id": str(user_id), "workout_type": 1,
        "version": created["version"], "session": {"session_id": session_id, "deleted": True},
    }).json()
    assert deleted == {"ok": True, "session": {"session_id": session_id, "deleted": True}, "version": 3}
    with factory() as db:
        state = db.scalar(select(StrengthState).where(StrengthState.user_id == user_id))
        assert state.workouts == []


def test_strength_every_write_requires_an_expected_version():
    client, factory = make_client()
    with factory() as db:
        user = add_user(db, "strength-version-required@example.test", "Версия")
        db.add(StrengthState(user_id=user.id, workout_types=[], hidden_exercises=[], workouts=[]))
        db.commit()
        user_id = user.id

    login(client)
    requests = [
        {"action": "saveSession", "target_user_id": str(user_id), "workout_type": 1, "session": {"exercises": []}},
        {"action": "saveExerciseSettings", "target_user_id": str(user_id), "workout_type": 1, "exercises": []},
        {"action": "saveExerciseCatalog", "target_user_id": str(user_id), "workout_type": 1, "exercises": []},
    ]
    for body in requests:
        response = client.post("/api/apps/strength", json=body)
        assert response.status_code == 200
        assert response.json() == {"ok": False, "error": "STRENGTH_STATE_VERSION_REQUIRED"}


def test_strength_import_refuses_any_existing_profile_state():
    _, factory = make_client()
    with factory() as db:
        user = User(display_name="Уже есть", status="active", data_origin="legacy_import")
        db.add(user)
        db.flush()
        db.add(StrengthState(
            user_id=user.id,
            workout_types=[{"workout_type": 1, "title": "Нельзя заменить"}],
            hidden_exercises=[],
            workouts=[],
        ))
        db.commit()

        payload = {
            "strength_users": [["user_id", "display_name", "email", "status"], ["legacy-existing", "Уже есть", "", "active"]],
            "strength_types": [], "strength_catalog": [], "strength_sessions": [],
            "strength_session_exercises": [], "strength_sets": [],
        }
        with pytest.raises(ValueError, match="STRENGTH_IMPORT_REQUIRES_EXPLICIT_REPLACE"):
            import_strength(db, payload, defaultdict(int))
        state = db.scalar(select(StrengthState).where(StrengthState.user_id == user.id))
        assert state.workout_types == [{"workout_type": 1, "title": "Нельзя заменить"}]


def test_strength_catalog_is_account_wide_and_template_membership_is_separate():
    client, factory = make_client()
    with factory() as db:
        user = add_user(db, "catalog@example.test", "Каталог")
        db.add(StrengthState(
            user_id=user.id,
            workout_types=[],
            hidden_exercises=[{
                "scope": "catalog",
                "exercise_id": "custom-old-row",
                "exercise_name": "Моя старая тяга",
                "catalog_active": True,
                "source": "custom",
            }],
            workouts=[{
                "workout_type": 1,
                "session_number": 1,
                "session_id": "legacy-1",
                "date": "2026-09-01",
                "exercises": [{
                    "exercise_id": "legacy-cable-row",
                    "exercise_name": "Тяга блока из старой истории",
                    "sort_order": 1,
                    "sets": [],
                }, {
                    "exercise_id": "custom-old-row",
                    "exercise_name": "Моя старая тяга",
                    "sort_order": 2,
                    "sets": [{"set_number": 1, "fact_weight": "25", "fact_reps": "12"}],
                }],
            }],
        ))
        db.commit()
        user_id = user.id

    denied_requests = [
        client.get(f"/api/apps/strength?action=openUser&target_user_id={user_id}"),
        client.get(f"/api/apps/strength?action=getWorkout&target_user_id={user_id}&type=1"),
        client.post("/api/apps/strength", json={"action": "saveExerciseSettings", "target_user_id": str(user_id), "workout_type": 1, "exercises": []}),
        client.post("/api/apps/strength", json={"action": "saveExerciseCatalog", "target_user_id": str(user_id), "workout_type": 1, "exercises": []}),
        client.post("/api/apps/strength", json={"action": "saveSession", "target_user_id": str(user_id), "workout_type": 1, "session": {"session_number": 1, "exercises": []}}),
    ]
    assert [response.status_code for response in denied_requests] == [401, 401, 401, 401, 401]

    login(client)
    first = client.get(
        "/api/apps/strength",
        params={"action": "getWorkout", "target_user_id": str(user_id), "type": 1},
    ).json()["workout"]["exercise_catalog"]
    second = client.get(
        "/api/apps/strength",
        params={"action": "getWorkout", "target_user_id": str(user_id), "type": 2},
    ).json()["workout"]["exercise_catalog"]

    assert len([item for item in first if item["source"] == "base"]) == 25
    base_names = {item["name"] for item in BASE_STRENGTH_EXERCISES}
    assert base_names == {
        "Жим штанги лёжа",
        "Жим лёжа узким хватом",
        "Жим гантелей на наклонной скамье",
        "Подтягивания в гравитроне",
        "Тяга верхнего блока сидя",
        "Тяга горизонтального блока",
            "Подтягивания",
            "Тяга гантели в наклоне",
            "Тяга штанги в наклоне",
        "Приседания со штангой",
        "Жим ногами",
        "Выпады",
        "Румынская тяга",
        "Становая тяга",
        "Ягодичный мост",
        "Сгибание ног в тренажёре",
        "Разгибание ног в тренажёре",
        "Сведение ног в тренажёре",
        "Разведение ног в тренажёре",
        "Подъёмы на носки",
        "Сгибание рук с гантелями",
        "Тяга верхнего блока на трицепс",
        "Разведение гантелей в стороны",
        "Разведение рук на заднюю дельту",
        "Подъём гантелей на бицепс сидя на наклонной скамье",
    }
    assert all(
        item["muscles"].strip()
        and len(item["tips"]) >= 3
        and all(tip.strip() for tip in item["tips"])
        for item in BASE_STRENGTH_EXERCISES
    )
    assert {item["exercise_id"] for item in first} == {item["exercise_id"] for item in second}
    assert next(item for item in first if item["exercise_id"] == "legacy-cable-row")["active"] is True
    assert next(item for item in second if item["exercise_id"] == "legacy-cable-row")["active"] is False

    saved = client.post(
        "/api/apps/strength",
        json={
            "action": "saveExerciseCatalog",
            "target_user_id": str(user_id),
            "workout_type": 2,
            "version": 1,
            "exercises": [
                {
                    "exercise_id": "bench-press",
                    "exercise_name": "Нельзя переименовать базовое",
                    "active": True,
                    "sort_order": 1,
                    "source": "base",
                },
                    {
                        "exercise_id": "custom-my-row",
                        "exercise_name": "Моя тяга",
                        "active": True,
                        "catalog_active": True,
                        "sort_order": 2,
                        "source": "custom",
                    },
                    {
                        "exercise_id": "custom-old-row",
                        "exercise_name": "Моя старая тяга",
                        "active": False,
                        "catalog_active": True,
                        "sort_order": 3,
                        "source": "custom",
                    },
            ],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["ok"] is True
    version = saved.json()["version"]

    loaded = client.get(
        "/api/apps/strength",
        params={"action": "getWorkout", "target_user_id": str(user_id), "type": 2},
    ).json()["workout"]["exercise_catalog"]
    assert next(item for item in loaded if item["exercise_id"] == "bench-press")["exercise_name"] == "Жим штанги лёжа"
    assert next(item for item in loaded if item["exercise_id"] == "bench-press")["active"] is True
    assert next(item for item in loaded if item["exercise_id"] == "custom-my-row")["active"] is True
    loaded_other_template = client.get(
        "/api/apps/strength",
        params={"action": "getWorkout", "target_user_id": str(user_id), "type": 1},
    ).json()["workout"]["exercise_catalog"]
    custom_elsewhere = next(item for item in loaded_other_template if item["exercise_id"] == "custom-my-row")
    assert custom_elsewhere["catalog_active"] is True
    assert custom_elsewhere["active"] is False

    hidden = client.post(
        "/api/apps/strength",
        json={
            "action": "saveExerciseCatalog",
            "target_user_id": str(user_id),
            "workout_type": 1,
            "version": version,
            "exercises": [
                {
                    "exercise_id": "legacy-cable-row",
                    "exercise_name": "Тяга блока из старой истории",
                    "active": False,
                    "sort_order": 1,
                    "source": "history",
                },
                {
                    "exercise_id": "custom-old-row",
                    "exercise_name": "Моя старая тяга",
                    "active": False,
                    "catalog_active": False,
                    "sort_order": 2,
                    "source": "custom",
                },
            ],
        },
    )
    assert hidden.status_code == 200
    after_hide = client.get(
        "/api/apps/strength",
        params={"action": "getWorkout", "target_user_id": str(user_id), "type": 1},
    ).json()["workout"]
    assert next(
        item for item in after_hide["exercise_catalog"]
        if item["exercise_id"] == "legacy-cable-row"
    )["active"] is False
    assert any(
        item["exercise_id"] == "legacy-cable-row"
        for item in after_hide["session_exercises"]
    )
    assert next(
        item for item in after_hide["exercise_catalog"]
        if item["exercise_id"] == "custom-old-row"
    )["catalog_active"] is False
    assert any(
        item["exercise_id"] == "custom-old-row"
        for item in after_hide["session_exercises"]
    )
    assert any(
        item["exercise_id"] == "custom-old-row" and item["fact_weight"] == "25"
        for item in after_hide["sets"]
    )


def test_dqs_managed_runtime_uses_admin_session_and_writes_audit():
    client, factory = make_client()
    with factory() as db:
        user = add_user(db, "dqs@example.test", "Дневник DQS")
        other = add_user(db, "other-dqs@example.test", "Другой дневник")
        db.add(DqsState(
            user_id=user.id,
            start_date="2026-09-01",
            days={},
        ))
        db.add(DqsState(
            user_id=other.id,
            start_date="2026-09-02",
            days={"1": {"p": [1] * 17, "d": [True] * 17}},
        ))
        db.commit()
        user_id = user.id
        other_id = other.id

    login(client)
    opened = client.post(
        f"/admin/api/apps/dqs/users/{user_id}/runtime",
        json={"action": "openUser"},
    )
    assert opened.status_code == 200
    assert opened.json()["email"] == "dqs@example.test"

    saved = client.post(
        f"/admin/api/apps/dqs/users/{user_id}/runtime",
        json={
            "action": "saveDay",
            "day": "1",
            "data": '{"p":[' + ",".join(["0"] * 17) + '],"d":[' + ",".join(["null"] * 17) + "]}",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["ok"] is True
    with factory() as db:
        target_state = db.scalar(select(DqsState).where(DqsState.user_id == user_id))
        other_state = db.scalar(select(DqsState).where(DqsState.user_id == other_id))
        assert target_state.days["1"]["p"] == [0] * 17
        assert other_state.days["1"]["p"] == [1] * 17
        edit = db.scalar(
            select(AdminAppEdit).where(
                AdminAppEdit.target_user_id == user_id,
                AdminAppEdit.app_code == "dqs",
            )
        )
        assert edit is not None
        assert edit.action == "saveDay"


def test_metabolism_managed_runtime_updates_only_target_and_writes_audit():
    client, factory = make_client()
    with factory() as db:
        target = add_user(db, "metabolism-target@example.test", "Целевой профиль")
        other = add_user(db, "metabolism-other@example.test", "Другой профиль")
        db.add(MetabolismState(
            user_id=target.id,
            variants={"1": {"weight": 80}},
            active_variant=1,
            version=1,
        ))
        db.add(MetabolismState(
            user_id=other.id,
            variants={"1": {"weight": 65}},
            active_variant=1,
            version=1,
        ))
        db.commit()
        target_id = target.id
        other_id = other.id

    login(client)
    loaded = client.get(f"/admin/api/apps/metabolism/users/{target_id}/runtime")
    assert loaded.status_code == 200
    assert loaded.json()["variants"]["1"]["weight"] == 80

    saved = client.put(
        f"/admin/api/apps/metabolism/users/{target_id}/runtime",
        json={"variants": {"1": {"weight": 79}}, "activeVariant": 1, "version": 1},
    )
    assert saved.status_code == 200
    assert saved.json()["version"] == 2

    with factory() as db:
        target_state = db.scalar(select(MetabolismState).where(MetabolismState.user_id == target_id))
        other_state = db.scalar(select(MetabolismState).where(MetabolismState.user_id == other_id))
        assert target_state.variants["1"]["weight"] == 79
        assert other_state.variants["1"]["weight"] == 65
        edit = db.scalar(select(AdminAppEdit).where(
            AdminAppEdit.target_user_id == target_id,
            AdminAppEdit.app_code == "metabolism",
        ))
        assert edit is not None
        assert edit.action == "save_state"


def test_managed_app_runtime_on_public_host_still_requires_admin_session():
    _, factory = make_client()
    with factory() as db:
        user = add_user(db, "managed@example.test", "Управляемый профиль")
        db.add(DqsState(user_id=user.id, days={}))
        db.commit()
        user_id = user.id

    public_client = TestClient(app, base_url="https://edabalans.ru")
    denied = public_client.get(
        f"/api/apps/dqs?action=openUser&target_user_id={user_id}"
    )
    assert denied.status_code == 401

    login(public_client)
    allowed = public_client.post(
        f"/admin/api/apps/dqs/users/{user_id}/runtime",
        json={"action": "openUser"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["email"] == "managed@example.test"

    saved = public_client.post(
        "/api/apps/strength",
        json={
            "action": "saveExerciseSettings",
            "target_user_id": str(user_id),
            "workout_type": 1,
            "exercises": [],
        },
    )
    assert saved.status_code == 404
    assert saved.json()["detail"] == "application state not found"
