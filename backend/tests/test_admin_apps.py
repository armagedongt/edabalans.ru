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
    client = TestClient(app, base_url="https://testserver")
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
