import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Payment,
    Product,
    ProductAccessRule,
    ProductAlias,
    Resource,
    User,
    UserAccess,
    UserEmail,
    UserPhone,
)

TOKEN = "test-tilda-token"
HEADERS = {"X-Tilda-Webhook-Token": TOKEN}


def make_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with session_factory() as session:
            yield session

    def override_settings() -> Settings:
        return Settings(
            database_url="sqlite+pysqlite:///:memory:",
            tilda_webhook_token=TOKEN,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    return TestClient(app), session_factory


def seed_catalog(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as db:
        product = Product(code="MASTERCLASS_RECIPES", name="Мастер-класс + рецепты")
        resource = Resource(code="ACCESS_MASTERCLASS", name="Мастер-класс")
        db.add_all([product, resource])
        db.flush()
        db.add_all(
            [
                ProductAlias(
                    product_id=product.id,
                    source="google_payments_legacy",
                    raw_name_exact="Мастер-класс. Стандарт",
                ),
                ProductAccessRule(product_id=product.id, resource_id=resource.id),
            ]
        )
        db.commit()


def paid_payload() -> dict[str, str]:
    return {
        "Name": "Тестовый клиент",
        "Email": "Client@Example.Test",
        "Phone": "+7 (999) 123-45-67",
        "paymentsystem": "robokassa",
        "orderid": "order-1001",
        "paymentid": "payment-1001",
        "products": "Мастер-класс. Стандарт",
        "price": "4 990,00",
        "Currency": "RUB",
        "Payment status": "Paid",
        "referer": "https://example.test/buy?utm_source=tilda",
        "formid": "form123",
        "Form name": "Корзина",
        "sent": "2026-08-22 12:30:00",
        "requestid": "request-1001",
        "ma_name": "Тестовый клиент",
        "ma_email": "Client@Example.Test",
        "ma_phone": "+7 (999) 123-45-67",
    }


def test_tilda_handshake_requires_secret_and_does_not_write() -> None:
    client, session_factory = make_client()
    assert client.post("/integrations/tilda/payments", data={"test": "test"}).status_code == 401
    response = client.post(
        "/integrations/tilda/payments", data={"test": "test"}, headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    with session_factory() as db:
        assert db.scalar(select(func.count(Payment.id))) == 0
    app.dependency_overrides.clear()


def test_paid_order_is_written_to_client_payment_and_access() -> None:
    client, session_factory = make_client()
    seed_catalog(session_factory)

    response = client.post(
        "/integrations/tilda/payments", data=paid_payload(), headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json()["status"] == "saved"
    assert response.json()["access"] == "granted"

    with session_factory() as db:
        payment = db.scalar(select(Payment))
        user = db.scalar(select(User))
        assert payment is not None and user is not None
        assert payment.user_id == user.id
        assert payment.source == "tilda_webhook"
        assert payment.external_order_id == "order-1001"
        assert payment.external_payment_id == "payment-1001"
        assert str(payment.amount) == "4990.00"
        assert payment.currency == "RUB"
        assert payment.payment_status == "paid"
        assert payment.raw_payload["requestid"] == "request-1001"
        assert db.scalar(select(UserEmail.email_normalized)) == "client@example.test"
        assert db.scalar(select(UserPhone.phone_normalized)) == "+79991234567"
        assert db.scalar(select(func.count(UserAccess.id))) == 1

    duplicate = client.post(
        "/integrations/tilda/payments", data=paid_payload(), headers=HEADERS
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    with session_factory() as db:
        assert db.scalar(select(func.count(Payment.id))) == 1
        assert db.scalar(select(func.count(UserAccess.id))) == 1
    app.dependency_overrides.clear()


def test_unknown_product_is_saved_without_access() -> None:
    client, session_factory = make_client()
    payload = paid_payload()
    payload["orderid"] = "order-unmapped"
    payload["paymentid"] = "payment-unmapped"
    payload["products"] = "Новый неизвестный тариф"

    response = client.post(
        "/integrations/tilda/payments", data=payload, headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json()["status"] == "saved_unmapped_product"
    assert response.json()["access"] == "not_granted"
    with session_factory() as db:
        payment = db.scalar(select(Payment))
        assert payment is not None
        assert payment.product_id is None
        assert db.scalar(select(func.count(UserAccess.id))) == 0
    app.dependency_overrides.clear()
