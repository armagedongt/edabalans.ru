import os
from datetime import datetime, timezone

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
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AdminAppEdit,
    DqsState,
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

    login(client)
    response = client.get("/admin/api/apps/users?app_code=dqs")
    assert response.status_code == 200
    rows = {row["email"]: row for row in response.json()["users"]}
    assert rows["access@example.test"]["has_access"] is True
    assert rows["access@example.test"]["has_state"] is False
    assert rows["state@example.test"]["has_access"] is False
    assert rows["state@example.test"]["has_state"] is True

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
        '"workout_type":1,"exercises":[]}' % user_id
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
        db.add(DqsState(
            user_id=user.id,
            start_date="2026-09-01",
            days={},
        ))
        db.commit()
        user_id = user.id

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
        edit = db.scalar(
            select(AdminAppEdit).where(
                AdminAppEdit.target_user_id == user_id,
                AdminAppEdit.app_code == "dqs",
            )
        )
        assert edit is not None
        assert edit.action == "saveDay"


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
