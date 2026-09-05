import os
from datetime import UTC, datetime

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("APP_AUTH_SECRET", "test-account-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.account_auth_routes import _attempts  # noqa: E402
from app.account_onboarding_service import (  # noqa: E402
    account_access_email,
    ensure_paid_account_onboarding,
    onboarding_links,
)
from app.account_security import generate_password, password_hash, verify_password  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
import app.main as main_module  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AccountCredential, AccountOnboarding, Payment, User, UserEmail  # noqa: E402


def settings() -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_auth_secret="test-account-secret",
        account_telegram_bot_username="test_tg_bot",
        account_max_bot_username="test_max_bot",
        account_onboarding_enabled=True,
        account_email_worker_enabled=False,
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

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = settings
    main_module.SessionLocal = factory
    _attempts.clear()
    return TestClient(app, base_url="https://go.example.test"), factory


def seed_credential(factory: sessionmaker[Session]) -> None:
    with factory() as db:
        user = User(display_name="Клиент", status="active")
        db.add(user)
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
                AccountCredential(
                    user_id=user.id,
                    password_hash=password_hash("Test-Password-9", "test-account-secret"),
                    password_version=1,
                    issued_via="telegram",
                ),
            ]
        )
        db.commit()


def test_password_hash_is_one_way_and_password_is_human_readable():
    password = generate_password()
    encoded = password_hash(password, "pepper")

    assert len(password) == 8
    assert password.isalnum()
    assert not set(password) & set("O0Il1")
    assert password not in encoded
    assert verify_password(password, encoded, "pepper") is True
    assert verify_password(password + "x", encoded, "pepper") is False
    assert verify_password(password, encoded, "another-pepper") is False


def test_login_sets_remembered_http_only_session_and_logout_revokes_it():
    client, factory = setup()
    seed_credential(factory)

    rejected = client.post(
        "/api/account-auth/login",
        json={"email": "member@example.test", "password": "wrong-password"},
    )
    assert rejected.status_code == 401

    accepted = client.post(
        "/api/account-auth/login",
        json={"email": "Member@Example.Test", "password": "Test-Password-9"},
    )
    assert accepted.status_code == 200
    cookie = accepted.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert client.get("/api/account-auth/session").json()["authenticated"] is True

    cross_account = client.get("/api/account?email=someone-else@example.test")
    assert cross_account.status_code == 403
    cross_account_write = client.post(
        "/api/access/registration-seen",
        json={"email": "someone-else@example.test"},
    )
    assert cross_account_write.status_code == 403
    own_account_write = client.post(
        "/api/access/registration-seen",
        json={"email": "member@example.test"},
    )
    assert own_account_write.status_code == 200
    assert client.get("/api/account-auth/account").status_code == 200

    assert client.post("/api/account-auth/logout").status_code == 200
    assert client.get("/api/account-auth/session").json()["authenticated"] is False
    app.dependency_overrides.clear()


def test_paid_payment_creates_one_idempotent_onboarding_with_two_platform_links():
    _, factory = setup()
    with factory() as db:
        user = User(display_name="Клиент", status="active")
        db.add(user)
        db.flush()
        db.add(
            UserEmail(
                user_id=user.id,
                email_original="member@example.test",
                email_normalized="member@example.test",
                is_primary=True,
                source="test",
            )
        )
        payment = Payment(
            user_id=user.id,
            source="test",
            external_order_id="order-1",
            product_name_raw="Мастер-класс",
            payment_status="paid",
            paid_at=datetime.now(UTC),
        )
        db.add(payment)
        db.flush()

        first = ensure_paid_account_onboarding(db, payment, settings())
        second = ensure_paid_account_onboarding(db, payment, settings())
        db.commit()

        assert first.id == second.id
        assert db.scalar(select(AccountOnboarding).where(AccountOnboarding.payment_id == payment.id))
        links = onboarding_links(first, settings())
        assert links["telegram"].startswith("https://t.me/test_tg_bot?start=M")
        assert links["max"].startswith("https://max.ru/test_max_bot?start=M")
    app.dependency_overrides.clear()


def test_account_access_email_contains_claim_links_but_not_a_password():
    message = account_access_email(
        email="member@example.test",
        links={
            "telegram": "https://t.me/test_tg_bot?start=Mtelegram",
            "max": "https://max.ru/test_max_bot?start=Mmax",
        },
        expires_at=datetime.now(UTC),
        settings=Settings(
            database_url="sqlite+pysqlite:///:memory:",
            app_auth_secret="test-account-secret",
            smtp_from_email="cabinet@example.test",
            smtp_reply_to="owner@example.test",
        ),
    )

    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "https://t.me/test_tg_bot?start=Mtelegram" in plain
    assert "https://max.ru/test_max_bot?start=Mmax" in plain
    assert "Пароль:" not in plain
    assert "Mtelegram" in html and "Mmax" in html
