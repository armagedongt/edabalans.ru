import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import app_auth  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Resource, User, UserAccess, UserEmail  # noqa: E402


def setup() -> tuple[TestClient, sessionmaker[Session]]:
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

    def override_settings() -> Settings:
        return Settings(
            database_url="sqlite+pysqlite:///:memory:",
            admin_password="test-app-secret",
            smtp_host="smtp.example.test",
            smtp_from_email="owner@example.test",
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    with factory() as db:
        user = User(display_name="Участник", status="active")
        resource = Resource(
            code="ACCESS_MASTERCLASS", name="Мастер-класс", status="active"
        )
        db.add_all([user, resource])
        db.flush()
        db.add_all(
            [
                UserEmail(
                    user_id=user.id,
                    email_original="member@example.test",
                    email_normalized="member@example.test",
                    is_primary=True,
                    source="test",
                ),
                UserAccess(
                    user_id=user.id,
                    resource_id=resource.id,
                    source="test",
                    granted_at=datetime.now(timezone.utc),
                ),
            ]
        )
        db.commit()
    app_auth._last_challenge.clear()
    app_auth._challenge_attempts.clear()
    return TestClient(app), factory


def test_email_code_creates_session_and_unlocks_only_matching_email(monkeypatch):
    client, _ = setup()
    delivered = {}

    def capture(email: str, code: str, settings: Settings) -> None:
        delivered.update(email=email, code=code)

    monkeypatch.setattr(app_auth, "send_login_code", capture)
    challenge = client.post(
        "/api/app-auth/challenge", json={"email": "Member@Example.Test"}
    )
    assert challenge.status_code == 200
    assert delivered["email"] == "member@example.test"

    wrong = client.post(
        "/api/app-auth/verify",
        json={
            "challenge_token": challenge.json()["challenge_token"],
            "code": "000000" if delivered["code"] != "000000" else "111111",
        },
    )
    assert wrong.status_code == 401

    verified = client.post(
        "/api/app-auth/verify",
        json={
            "challenge_token": challenge.json()["challenge_token"],
            "code": delivered["code"],
        },
    )
    assert verified.status_code == 200
    token = verified.json()["session_token"]

    opened = client.get(
        "/api/masterclass/questionnaires/onboarding?email=member@example.test",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert opened.status_code == 200
    mismatched = client.get(
        "/api/masterclass/questionnaires/onboarding?email=other@example.test",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert mismatched.status_code == 401
    app.dependency_overrides.clear()


def test_challenge_is_rate_limited(monkeypatch):
    client, _ = setup()
    monkeypatch.setattr(app_auth, "send_login_code", lambda *_: None)
    first = client.post(
        "/api/app-auth/challenge", json={"email": "member@example.test"}
    )
    second = client.post(
        "/api/app-auth/challenge", json={"email": "member@example.test"}
    )
    assert first.status_code == 200
    assert second.status_code == 429
    app.dependency_overrides.clear()


def test_first_challenge_is_allowed_during_first_process_minute(monkeypatch):
    client, _ = setup()
    monkeypatch.setattr(app_auth.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(app_auth, "send_login_code", lambda *_: None)

    first = client.post(
        "/api/app-auth/challenge", json={"email": "member@example.test"}
    )

    assert first.status_code == 200
    app.dependency_overrides.clear()


def test_malformed_bearer_token_is_rejected_without_server_error():
    client, _ = setup()
    response = client.get(
        "/api/masterclass/questionnaires/onboarding?email=member@example.test",
        headers={"Authorization": "Bearer !!!.not-a-signature"},
    )
    assert response.status_code == 401
    app.dependency_overrides.clear()


def test_email_code_allows_only_five_attempts_and_is_one_time(monkeypatch):
    client, _ = setup()
    delivered = {}
    monkeypatch.setattr(
        app_auth,
        "send_login_code",
        lambda email, code, settings: delivered.update(email=email, code=code),
    )
    challenge = client.post(
        "/api/app-auth/challenge", json={"email": "member@example.test"}
    ).json()["challenge_token"]
    wrong_code = "000000" if delivered["code"] != "000000" else "111111"
    for _ in range(5):
        assert client.post(
            "/api/app-auth/verify",
            json={"challenge_token": challenge, "code": wrong_code},
        ).status_code == 401
    assert client.post(
        "/api/app-auth/verify",
        json={"challenge_token": challenge, "code": delivered["code"]},
    ).status_code == 429

    app_auth._last_challenge.clear()
    fresh = client.post(
        "/api/app-auth/challenge", json={"email": "member@example.test"}
    ).json()["challenge_token"]
    assert client.post(
        "/api/app-auth/verify",
        json={"challenge_token": fresh, "code": delivered["code"]},
    ).status_code == 200
    assert client.post(
        "/api/app-auth/verify",
        json={"challenge_token": fresh, "code": delivered["code"]},
    ).status_code == 429
    app.dependency_overrides.clear()
