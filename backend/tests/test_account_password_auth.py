import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("APP_AUTH_SECRET", "test-account-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.account_auth_routes import _attempts, _registration_attempts  # noqa: E402
import app.account_onboarding_service as onboarding_service  # noqa: E402
from app.account_onboarding_service import (  # noqa: E402
    account_access_email,
    account_onboarding_configuration_error,
    ensure_free_account_onboarding,
    ensure_paid_account_onboarding,
    onboarding_links,
)
from app.account_security import (  # noqa: E402
    generate_password,
    password_hash,
    token_hash,
    verify_password,
)
from app.access_routes import account_courses  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
import app.main as main_module  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AccountCredential,
    AccountOnboarding,
    MessengerLinkToken,
    Payment,
    User,
    UserAccess,
    UserEmail,
)


def settings() -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_auth_secret="test-account-secret",
        account_telegram_bot_username="test_tg_bot",
        account_max_bot_username="test_max_bot",
        account_onboarding_enabled=True,
        account_email_worker_enabled=True,
        smtp_host="smtp.example.test",
        smtp_username="smtp-user",
        smtp_password="smtp-secret",
        smtp_from_email="cabinet@example.test",
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
    _registration_attempts.clear()
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


def test_email_registration_creates_no_access_user_and_one_reusable_onboarding():
    client, factory = setup()

    response = client.post(
        "/api/account-auth/register",
        json={"email": "New.Member@Example.Test"},
    )

    assert response.status_code == 200
    assert "Проверьте почту" in response.json()["message"]
    repeated = client.post(
        "/api/account-auth/register",
        json={"email": "new.member@example.test"},
    )
    assert repeated.status_code == 200
    with factory() as db:
        user = db.scalar(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_normalized == "new.member@example.test")
        )
        assert user is not None
        assert user.access_review_status == "not_required"
        assert db.get(AccountCredential, user.id) is None
        assert db.scalar(select(Payment.id).where(Payment.user_id == user.id)) is None
        assert db.scalar(select(UserAccess.id).where(UserAccess.user_id == user.id)) is None
        onboarding = db.scalar(select(AccountOnboarding).where(AccountOnboarding.user_id == user.id))
        assert onboarding is not None
        assert onboarding.payment_id is None
        onboardings = list(
            db.scalars(
                select(AccountOnboarding).where(AccountOnboarding.user_id == user.id)
            )
        )
        assert len(onboardings) == 1
        links = onboarding_links(onboarding, settings())
        assert links["telegram"].startswith("https://t.me/test_tg_bot?start=M")
        tokens = {
            row.platform: row
            for row in db.scalars(
                select(MessengerLinkToken).where(
                    MessengerLinkToken.account_onboarding_id == onboarding.id
                )
            )
        }
        assert set(tokens) == {"telegram", "max"}
        for platform, link in links.items():
            raw_token = parse_qs(urlparse(link).query)["start"][0]
            assert tokens[platform].token_hash == token_hash(raw_token)
    app.dependency_overrides.clear()


def test_registration_limits_valid_requests_per_ip():
    client, _ = setup()
    for number in range(5):
        response = client.post(
            "/api/account-auth/register",
            json={"email": f"member-{number}@example.test"},
        )
        assert response.status_code == 200
    blocked = client.post(
        "/api/account-auth/register",
        json={"email": "member-6@example.test"},
    )
    assert blocked.status_code == 429
    app.dependency_overrides.clear()


def test_free_onboarding_worker_sends_the_generated_messenger_links(monkeypatch):
    _, factory = setup()
    with factory() as db:
        onboarding = ensure_free_account_onboarding(
            db, "new.member@example.test", settings()
        )
        assert onboarding is not None
        expected_links = onboarding_links(onboarding, settings())
        db.commit()

    delivered = []
    monkeypatch.setattr(onboarding_service, "SessionLocal", factory)
    monkeypatch.setattr(
        onboarding_service,
        "_send_message",
        lambda message, _settings: delivered.append(message),
    )

    assert onboarding_service.process_due_account_email(settings()) is True
    assert len(delivered) == 1
    plain = delivered[0].get_body(preferencelist=("plain",)).get_content()
    assert expected_links["telegram"] in plain
    assert expected_links["max"] in plain
    assert "Регистрация почти готова" in plain
    with factory() as db:
        row = db.get(AccountOnboarding, onboarding.id)
        assert row is not None
        assert row.email_status == "sent"
    app.dependency_overrides.clear()


def test_account_portal_exposes_the_registration_entry():
    client, _ = setup()

    response = client.get("/lk?mode=register")

    assert response.status_code == 200
    assert 'href="/lk?mode=register"' in response.text
    assert "function register()" in response.text
    assert "/api/account-auth/register" in response.text
    assert "Электронная почта" in response.text
    app.dependency_overrides.clear()


def test_empty_account_routes_masterclass_to_the_common_purchase_view():
    account_app = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "apps" / "account.html"
    ).read_text(encoding="utf-8")

    assert 'data-public-masterclass="true"' in account_app
    assert "public_masterclass_tariffs" in account_app
    assert 'data-edabalans-app="masterclass-offers"' in account_app
    assert "data-edabalans-public-masterclass" in account_app
    assert "publicMasterclassTariffs" not in account_app
    masterclass_script = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "masterclass.js"
    ).read_text(encoding="utf-8")
    assert "function publicTariffs" in masterclass_script
    assert "ctx.publicMasterclass?publicTariffs:offers" in masterclass_script
    assert "api('/api/pricing/site')" in masterclass_script
    assert "Подробнее о программе" in masterclass_script
    embed_script = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "embed.js"
    ).read_text(encoding="utf-8")
    assert "data-edabalans-public-masterclass" in embed_script
    assert "publicMasterclass: publicMasterclass" in embed_script


def test_empty_account_masterclass_card_opens_public_tariffs_not_addon_offers():
    courses = account_courses(
        [
            {
                "account_code": "masterclass",
                "code": "MASTERCLASS",
                "name": "Мастер-класс",
                "description": "Описание",
                "resource": "ACCESS_MASTERCLASS",
                "status": "active",
                "ready": True,
                "app": "masterclass-course",
            },
            {
                "account_code": "recipes",
                "code": "RECIPES",
                "name": "Рецепты",
                "description": "Описание",
                "resource": "ACCESS_RECIPES",
                "status": "active",
                "ready": True,
                "app": "recipes",
            },
        ],
        set(),
        False,
    )

    masterclass = next(item for item in courses if item["code"] == "masterclass")
    recipes = next(item for item in courses if item["code"] == "recipes")
    assert masterclass["owned"] is False
    assert masterclass["purchase_mode"] == "public_masterclass_tariffs"
    assert recipes["purchase_mode"] is None


def test_account_registration_migration_makes_payment_optional():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260906_0037_account_registration.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "20260906_0037"' in migration
    assert 'down_revision = "20260905_0036"' in migration
    assert "ALTER TABLE account_onboardings ALTER COLUMN payment_id DROP NOT NULL" in migration


def test_free_onboarding_reuses_an_unclaimed_paid_delivery_when_available():
    _, factory = setup()
    with factory() as db:
        user = User(status="active")
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
            external_order_id="order-2",
            product_name_raw="Мастер-класс",
            payment_status="paid",
            paid_at=datetime.now(UTC),
        )
        db.add(payment)
        db.flush()
        paid = ensure_paid_account_onboarding(db, payment, settings())
        assert ensure_free_account_onboarding(db, "member@example.test", settings()).id == paid.id
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
        payment_completed=True,
    )

    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "https://t.me/test_tg_bot?start=Mtelegram" in plain
    assert "https://max.ru/test_max_bot?start=Mmax" in plain
    assert "Пароль:" not in plain
    assert "Mtelegram" in html and "Mmax" in html


def test_registration_email_does_not_claim_a_payment_or_product_access():
    message = account_access_email(
        email="member@example.test",
        links={"telegram": "https://t.me/test_tg_bot?start=Mtelegram", "max": ""},
        expires_at=datetime.now(UTC),
        settings=Settings(
            database_url="sqlite+pysqlite:///:memory:",
            app_auth_secret="test-account-secret",
            smtp_from_email="cabinet@example.test",
        ),
        payment_completed=False,
    )
    plain = message.get_body(preferencelist=("plain",)).get_content()
    assert "Регистрация почти готова" in plain
    assert "Оплата прошла" not in plain


def test_enabled_onboarding_requires_complete_delivery_configuration():
    incomplete = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_auth_secret="test-account-secret",
        account_onboarding_enabled=True,
    )
    error = account_onboarding_configuration_error(incomplete)

    assert error is not None
    assert "SMTP_HOST" in error
    assert "SMTP_PASSWORD" in error

    complete = settings().model_copy(
        update={
            "account_email_worker_enabled": True,
            "smtp_host": "smtp.example.test",
            "smtp_username": "smtp-user",
            "smtp_password": "smtp-secret",
            "smtp_from_email": "cabinet@example.test",
        }
    )
    assert account_onboarding_configuration_error(complete) is None
