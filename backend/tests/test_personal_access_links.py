import os
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    PersonalAccessLink,
    Resource,
    User,
    UserAccess,
    UserCoursePolicy,
    UserEmail,
    UserLegalAcceptance,
)


def setup():
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
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite+pysqlite:///:memory:",
        admin_username="admin@example.com",
        admin_password="test-admin-password",
    )
    client = TestClient(app, base_url="https://testserver")
    with factory() as db:
        user = User(
            display_name="Исторический клиент",
            status="active",
            access_review_status="pending",
            access_review_note="Историческая покупка требует решения Сергея",
        )
        other = User(display_name="Другой", status="active")
        db.add_all([user, other])
        db.flush()
        db.add_all([
            UserEmail(user_id=user.id, email_original="client@example.test", email_normalized="client@example.test", is_primary=True, source="test"),
            UserEmail(user_id=other.id, email_original="other@example.test", email_normalized="other@example.test", is_primary=True, source="test"),
            Resource(code="ACCESS_MASTERCLASS", name="Новый Мастер-класс", status="active"),
            Resource(code="ACCESS_CALORIES", name="Курс о калориях", status="active"),
        ])
        db.commit()
        user_id = user.id
    return client, factory, user_id


def login(client):
    response = client.post("/admin/api/login", json={
        "username": "admin@example.com",
        "password": "test-admin-password",
    })
    assert response.status_code == 200


def test_free_personal_link_is_bound_to_tilda_email_and_grants_once():
    client, factory, user_id = setup()
    login(client)
    created = client.post(
        f"/admin/api/users/{user_id}/personal-access-links",
        json={
            "resource_codes": ["ACCESS_MASTERCLASS", "ACCESS_CALORIES"],
            "final_amount": 0,
            "standard_amount": 10800,
            "expires_days": 14,
            "fully_unlocked": True,
        },
    )
    assert created.status_code == 200
    token = parse_qs(urlparse(created.json()["url"]).query)["access_token"][0]

    wrong = client.get(f"/api/access-links/{token}?email=other@example.test")
    assert wrong.status_code == 403
    opened = client.get(f"/api/access-links/{token}?email=client@example.test")
    assert opened.status_code == 200
    assert opened.json()["email"] == "client@example.test"
    assert opened.json()["mode"] == "free"

    first = client.post(
        f"/api/access-links/{token}/claim", json={"email": "client@example.test"}
    )
    second = client.post(
        f"/api/access-links/{token}/claim", json={"email": "client@example.test"}
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "claimed"
    with factory() as db:
        assert db.scalar(select(func.count(UserAccess.id))) == 2
        assert db.scalar(select(func.count(UserCoursePolicy.id))) == 2
        assert set(db.scalars(select(UserCoursePolicy.unlock_mode))) == {"fully_unlocked"}
        user = db.get(User, user_id)
        assert user.access_review_status == "completed"
        assert db.scalar(select(PersonalAccessLink.status)) == "claimed"
    app.dependency_overrides.clear()


def test_opening_account_page_moves_waiting_buyer_to_pending_without_granting_access():
    client, factory, user_id = setup()
    with factory() as db:
        user = db.get(User, user_id)
        user.access_review_status = "waiting_registration"
        user.tilda_access_status = "not_checked"
        db.commit()
    response = client.post(
        "/api/access/registration-seen",
        json={"email": "client@example.test"},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "review_required"
    with factory() as db:
        user = db.get(User, user_id)
        assert user.access_review_status == "pending"
        assert user.tilda_access_status == "pending"
        assert db.scalar(select(func.count(UserAccess.id))) == 0
    app.dependency_overrides.clear()


def test_universal_account_blocks_review_and_uses_server_resources_for_catalog():
    client, factory, user_id = setup()
    blocked = client.get("/api/account?email=client@example.test")
    assert blocked.status_code == 200
    assert blocked.json()["state"] == "review_required"
    assert blocked.json()["courses"] == []

    with factory() as db:
        user = db.get(User, user_id)
        user.access_review_status = "completed"
        masterclass = db.scalar(
            select(Resource).where(Resource.code == "ACCESS_MASTERCLASS")
        )
        db.add(
            UserAccess(
                user_id=user.id,
                resource_id=masterclass.id,
                source="test",
                granted_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    ready = client.get("/api/account?email=client@example.test")
    assert ready.status_code == 200
    data = ready.json()
    assert data["state"] == "ready"
    assert data["legal"]["required"] is True
    masterclass_card = next(item for item in data["courses"] if item["code"] == "masterclass")
    assert masterclass_card["state"] == "available"
    assert masterclass_card["app"] is None
    recipes_card = next(item for item in data["courses"] if item["code"] == "recipes")
    assert recipes_card["state"] == "not_owned"
    assert recipes_card["app"] is None

    accepted = client.post(
        "/api/account/legal-acceptances",
        json={
            "email": "client@example.test",
            "document_codes": [
                "educational_disclaimer",
                "personal_data_consent",
            ],
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["legal"]["required"] is False
    masterclass_card = next(
        item for item in accepted.json()["courses"] if item["code"] == "masterclass"
    )
    assert masterclass_card["app"] == "masterclass-course"
    repeated = client.post(
        "/api/account/legal-acceptances",
        json={
            "email": "client@example.test",
            "document_codes": [
                "educational_disclaimer",
                "personal_data_consent",
            ],
        },
    )
    assert repeated.status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count(UserLegalAcceptance.id))) == 2
    app.dependency_overrides.clear()
