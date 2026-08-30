import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")
os.environ.setdefault("APP_AUTH_SECRET", "test-client-session-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import app_auth  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.legal_service import LEGAL_DOCUMENTS  # noqa: E402
from app.models import (  # noqa: E402
    Resource,
    User,
    UserAccess,
    UserEmail,
    UserLegalAcceptance,
)


def test_legal_gate_summaries_use_owner_approved_copy_and_safe_storage_boundary():
    by_code = {item["code"]: item for item in LEGAL_DOCUMENTS}

    disclaimer = by_code["educational_disclaimer"]["summary"]
    assert disclaimer == (
        "Все материалы личного кабинета и мои консультации носят "
        "информационно-образовательный характер. Они не являются медицинской "
        "услугой, диагностикой или назначением лечения.\n\n"
        "При любых заболеваниях и патологиях рекомендации врача имеют "
        "приоритет над любой информацией, полученной от меня."
    )

    consent = by_code["personal_data_consent"]["summary"]
    assert consent == (
        "В личном кабинете хранятся данные вашего аккаунта — история "
        "покупок, прогресс обучения, анкета, дневник питания и любые другие "
        "сведения, которые вы укажете самостоятельно.\n\n"
        "По умолчанию данные хранятся только на территории РФ в соответствии "
        "с законом. Политика подробно объясняет "
        "состав данных, цели обработки, сроки хранения и ваши права."
    )


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
            app_auth_secret="test-client-session-secret",
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
                *[
                    UserLegalAcceptance(
                        user_id=user.id,
                        document_code=item["code"],
                        document_version=item["version"],
                        source="test",
                    )
                    for item in LEGAL_DOCUMENTS
                ],
            ]
        )
        db.commit()
    app_auth._last_challenge.clear()
    app_auth._challenge_attempts.clear()
    return TestClient(app), factory


def test_course_api_rejects_direct_access_before_current_legal_acceptances():
    client, factory = setup()
    with factory() as db:
        db.query(UserLegalAcceptance).delete()
        db.commit()

    response = client.get(
        "/api/masterclass/questionnaires/onboarding?email=member@example.test",
    )

    assert response.status_code == 403
    assert "личном кабинете" in response.json()["detail"]


def test_missing_legal_acceptances_do_not_block_identity_challenge(monkeypatch):
    client, factory = setup()
    with factory() as db:
        db.query(UserLegalAcceptance).delete()
        db.commit()
    monkeypatch.setattr(app_auth, "send_login_code", lambda *_: None)

    response = client.post(
        "/api/app-auth/challenge",
        json={"email": "member@example.test"},
    )

    assert response.status_code == 200


def test_email_code_session_no_longer_overrides_tilda_masterclass_identity(monkeypatch):
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
    assert mismatched.status_code == 403
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


def test_masterclass_transition_ignores_obsolete_bearer_token_and_uses_tilda_email():
    client, _ = setup()
    response = client.get(
        "/api/masterclass/questionnaires/onboarding?email=member@example.test",
        headers={"Authorization": "Bearer !!!.not-a-signature"},
    )
    assert response.status_code == 200
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


def test_pending_owner_review_blocks_existing_resource_access():
    client, factory = setup()
    with factory() as db:
        user = db.scalar(select(User).join(UserEmail).where(UserEmail.email_normalized == "member@example.test"))
        user.access_review_status = "pending"
        user.access_review_note = "Историческая покупка требует решения Сергея"
        db.commit()
    response = client.get(
        "/api/masterclass/course?email=member@example.test",
    )
    assert response.status_code == 403
    assert "подтверждения Сергея" in response.json()["detail"]
    app.dependency_overrides.clear()
