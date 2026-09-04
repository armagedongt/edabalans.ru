import os
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.masterclass_routes import offer_checkout_order  # noqa: E402
from app.tilda_service import checkout_resource_codes, find_offer_checkout  # noqa: E402
from app.models import (  # noqa: E402
    MasterclassEvent,
    MasterclassNotification,
    Payment,
    OfferCheckout,
    Product,
    ProductAccessRule,
    ProductAlias,
    Resource,
    User,
    UserAccess,
    UserEmail,
    UserPhone,
    UserOffer,
    PersonalAccessLink,
    UserCoursePolicy,
)

TOKEN = "test-tilda-token"
HEADERS = {"X-Tilda-Webhook-Token": TOKEN}


@pytest.mark.parametrize(("item", "expected"), [
    ("ACCESS_MASTERCLASS", ["ACCESS_MASTERCLASS", "dqs"]),
    ("recipes", ["ACCESS_RECIPES", "recipes"]),
    ("calories", ["ACCESS_CALORIES", "recipes", "metabolism"]),
    ("training", ["ACCESS_STRENGTH", "strength"]),
])
def test_checkout_resource_codes_preserve_primary_and_add_exact_companions(
    item: str, expected: list[str]
) -> None:
    every_active_resource = {
        "ACCESS_MASTERCLASS", "ACCESS_RECIPES", "ACCESS_CALORIES", "ACCESS_STRENGTH",
        "dqs", "recipes", "metabolism", "strength", "ACCESS_CONSULTATION",
    }
    assert checkout_resource_codes([item], every_active_resource) == expected


def test_checkout_resource_codes_require_the_primary_resource() -> None:
    with pytest.raises(ValueError, match="offer resources are not configured"):
        checkout_resource_codes(["ACCESS_MASTERCLASS"], {"dqs"})


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
        event = db.scalar(select(MasterclassEvent))
        assert event is not None
        assert event.event_type == "masterclass_purchase_confirmed"
        assert event.details["payment_id"] == str(payment.id)

    duplicate = client.post(
        "/integrations/tilda/payments", data=paid_payload(), headers=HEADERS
    )
    with session_factory() as db:
        assert db.scalar(select(func.count(MasterclassEvent.id))) == 1
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


def test_dynamic_offer_checkout_grants_exact_resources() -> None:
    client, session_factory = make_client()
    with session_factory() as db:
        user = User(display_name="Тестовый клиент", status="active")
        db.add(user); db.flush()
        db.add(UserEmail(user_id=user.id, email_original="Client@Example.Test", email_normalized="client@example.test", is_primary=True, source="test"))
        db.add_all([
            Resource(code="ACCESS_RECIPES", name="Рецепты"),
            Resource(code="ACCESS_CALORIES", name="Калории"),
        ])
        window_event = MasterclassEvent(
            user_id=user.id,
            event_key="offer:early:started",
            event_type="offer_window_started",
            placement="recipes-part-1-gate",
            occurred_at=datetime(2026, 8, 22, 8, tzinfo=timezone.utc),
            details={"stage": "early"},
        )
        db.add(window_event)
        db.flush()
        window = UserOffer(
            user_id=user.id,
            stage_code="early",
            started_at=datetime(2026, 8, 22, 8, tzinfo=timezone.utc),
            expires_at=datetime(2026, 8, 25, 8, tzinfo=timezone.utc),
            trigger_event_id=window_event.id,
            snapshot={},
        )
        db.add(window)
        db.flush()
        db.add(MasterclassNotification(
            user_id=user.id,
            event_id=window_event.id,
            notification_kind="sales_last_chance_due",
            deduplication_key="offer:early:started:sales_last_chance_due",
            due_at=datetime(2026, 8, 24, 8, tzinfo=timezone.utc),
            payload={"stage": "early"},
        ))
        checkout = OfferCheckout(
            user_id=user.id,
            checkout_kind="public_site",
            offer_code="bundle:digital",
            title="Комплект",
            items=["recipes", "calories"],
            amount=Decimal("3900"),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(checkout)
        db.flush()
        cart_command = offer_checkout_order(checkout, 3900)
        raw_product = cart_command.removeprefix("#order:").rsplit("=", 1)[0]
        db.commit()

    payload = paid_payload()
    payload.update({
        "orderid": "offer-order-1",
        "paymentid": "offer-payment-1",
        "products": raw_product,
        "price": "3900",
    })
    wrong_user_payload = dict(payload)
    wrong_user_payload.update({
        "orderid": "offer-order-wrong-user",
        "paymentid": "offer-payment-wrong-user",
        "Email": "other@example.test",
    })
    wrong_user = client.post(
        "/integrations/tilda/payments", data=wrong_user_payload, headers=HEADERS
    )
    assert wrong_user.status_code == 422
    with session_factory() as db:
        assert db.scalar(select(func.count(UserAccess.id))) == 0

    response = client.post("/integrations/tilda/payments", data=payload, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "saved"
    assert response.json()["access"] == "granted"
    with session_factory() as db:
        assert db.scalar(select(func.count(UserAccess.id))) == 2
        assert db.scalar(select(OfferCheckout.status)) == "paid"
        notification = db.scalar(select(MasterclassNotification))
        assert notification.status == "skipped"
        assert notification.error_message == "offer purchase confirmed during this window"
        window = db.scalar(select(UserOffer))
        assert window.started_at.replace(tzinfo=timezone.utc) == datetime(2026, 8, 22, 8, tzinfo=timezone.utc)
        assert window.expires_at.replace(tzinfo=timezone.utc) == datetime(2026, 8, 25, 8, tzinfo=timezone.utc)
        offer_event = db.scalar(
            select(MasterclassEvent).where(
                MasterclassEvent.event_type == "offer_purchase_confirmed"
            )
        )
        assert offer_event is not None
    app.dependency_overrides.clear()


def test_short_offer_reference_rejects_ambiguous_user_checkouts() -> None:
    _, session_factory = make_client()
    with session_factory() as db:
        user = User(display_name="Тестовый клиент", status="active")
        db.add(user)
        db.flush()
        db.add_all(
            [
                OfferCheckout(
                    id=uuid.UUID("12345678-0000-0000-0000-000000000001"),
                    user_id=user.id,
                    offer_code="single:recipes",
                    title="Система рецептов",
                    items=["recipes"],
                    amount=Decimal("2900"),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                ),
                OfferCheckout(
                    id=uuid.UUID("12345678-0000-0000-0000-000000000002"),
                    user_id=user.id,
                    offer_code="single:calories",
                    title="Калорийность рациона",
                    items=["calories"],
                    amount=Decimal("2900"),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                ),
            ]
        )
        db.flush()

        checkout, has_reference = find_offer_checkout(
            db, "Система рецептов · №12345678", user
        )

        assert has_reference is True
        assert checkout is None
    app.dependency_overrides.clear()


def test_short_offer_reference_finds_unbound_public_site_checkout() -> None:
    _, session_factory = make_client()
    with session_factory() as db:
        checkout = OfferCheckout(
            id=uuid.UUID("87654321-0000-0000-0000-000000000001"),
            user_id=None,
            checkout_kind="public_site",
            offer_code="site.masterclass.standard",
            title="Стандартный",
            items=["ACCESS_MASTERCLASS"],
            amount=Decimal("8900"),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(checkout)
        db.flush()

        found, has_reference = find_offer_checkout(
            db, "Стандартный · №87654321", None
        )

        assert has_reference is True
        assert found is not None
        assert found.id == checkout.id
    app.dependency_overrides.clear()


def test_short_offer_reference_finds_member_offer_before_email_resolution() -> None:
    _, session_factory = make_client()
    with session_factory() as db:
        user = User(display_name="Тестовый клиент", status="active")
        db.add(user)
        db.flush()
        checkout = OfferCheckout(
            id=uuid.UUID("76543210-0000-0000-0000-000000000001"),
            user_id=user.id,
            checkout_kind="member_offer",
            offer_code="single:recipes",
            title="Система рецептов",
            items=["recipes"],
            amount=Decimal("2900"),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(checkout)
        db.flush()

        found, has_reference = find_offer_checkout(
            db, "Система рецептов · №76543210", None
        )

        assert has_reference is True
        assert found is not None
        assert found.id == checkout.id
    app.dependency_overrides.clear()


def test_processing_offer_is_promoted_to_paid_and_grants_access_once() -> None:
    client, session_factory = make_client()
    with session_factory() as db:
        user = User(display_name="Тестовый клиент", status="active")
        db.add(user)
        db.flush()
        db.add(
            UserEmail(
                user_id=user.id,
                email_original="Client@Example.Test",
                email_normalized="client@example.test",
                is_primary=True,
                source="test",
            )
        )
        db.add_all(
            [
                Resource(code="ACCESS_RECIPES", name="Рецепты"),
                Resource(code="ACCESS_CALORIES", name="Калории"),
                Resource(code="recipes", name="Калькулятор рецептов"),
                Resource(code="metabolism", name="Калькулятор метаболизма"),
            ]
        )
        checkout = OfferCheckout(
            user_id=user.id,
            offer_code="bundle:digital",
            title="Комплект",
            items=["recipes", "calories"],
            amount=Decimal("3900"),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(checkout)
        db.commit()
        checkout_code = checkout.id.hex

    payload = paid_payload()
    payload.update(
        {
            "orderid": "offer-order-processing",
            "paymentid": "offer-payment-processing",
            "products": f"EB-{checkout_code} Комплект",
            "price": "3900",
            "Payment status": "processing",
        }
    )
    processing = client.post(
        "/integrations/tilda/payments", data=payload, headers=HEADERS
    )
    assert processing.status_code == 200
    assert processing.json()["status"] == "saved_without_access"
    assert processing.json()["access"] == "not_granted"
    payment_id = processing.json()["payment_id"]
    with session_factory() as db:
        assert db.scalar(select(func.count(Payment.id))) == 1
        assert db.scalar(select(func.count(UserAccess.id))) == 0
        assert db.scalar(select(OfferCheckout.status)) == "processing"

    payload["Payment status"] = "paid"
    paid = client.post(
        "/integrations/tilda/payments", data=payload, headers=HEADERS
    )
    assert paid.status_code == 200
    assert paid.json() == {
        "status": "updated_to_paid",
        "payment_id": payment_id,
        "access": "granted",
    }
    with session_factory() as db:
        payment = db.scalar(select(Payment))
        assert payment is not None
        assert payment.payment_status == "paid"
        assert db.scalar(select(func.count(Payment.id))) == 1
        assert db.scalar(select(func.count(UserAccess.id))) == 4
        assert db.scalar(select(OfferCheckout.status)) == "paid"

    duplicate = client.post(
        "/integrations/tilda/payments", data=payload, headers=HEADERS
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    with session_factory() as db:
        assert db.scalar(select(func.count(Payment.id))) == 1
        assert db.scalar(select(func.count(UserAccess.id))) == 4
    app.dependency_overrides.clear()


def test_processing_catalog_product_is_promoted_to_paid_once() -> None:
    client, session_factory = make_client()
    seed_catalog(session_factory)
    payload = paid_payload()
    payload["orderid"] = "catalog-order-processing"
    payload["paymentid"] = "catalog-payment-processing"
    payload["Payment status"] = "processing"

    processing = client.post(
        "/integrations/tilda/payments", data=payload, headers=HEADERS
    )
    assert processing.status_code == 200
    assert processing.json()["status"] == "saved_without_access"
    assert processing.json()["access"] == "not_granted"

    payload["Payment status"] = "paid"
    paid = client.post(
        "/integrations/tilda/payments", data=payload, headers=HEADERS
    )
    assert paid.status_code == 200
    assert paid.json()["status"] == "updated_to_paid"
    assert paid.json()["access"] == "granted"
    with session_factory() as db:
        assert db.scalar(select(func.count(Payment.id))) == 1
        assert db.scalar(select(func.count(UserAccess.id))) == 1

    duplicate = client.post(
        "/integrations/tilda/payments", data=payload, headers=HEADERS
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    with session_factory() as db:
        assert db.scalar(select(func.count(UserAccess.id))) == 1
    app.dependency_overrides.clear()


def test_paid_personal_link_grants_direct_resources_and_completes_review() -> None:
    client, session_factory = make_client()
    with session_factory() as db:
        user = User(
            display_name="Исторический клиент",
            status="active",
            access_review_status="pending",
        )
        db.add(user)
        db.flush()
        db.add(UserEmail(user_id=user.id, email_original="Client@Example.Test", email_normalized="client@example.test", is_primary=True, source="test"))
        db.add(Resource(code="ACCESS_MASTERCLASS", name="Новый Мастер-класс"))
        checkout = OfferCheckout(
            user_id=user.id,
            offer_code="personal:test",
            title="Персональное предложение",
            items=["ACCESS_MASTERCLASS"],
            amount=Decimal("1500"),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(checkout)
        db.flush()
        link = PersonalAccessLink(
            user_id=user.id,
            token_hash=hashlib.sha256(b"test-personal-token").hexdigest(),
            mode="paid",
            resource_codes=["ACCESS_MASTERCLASS"],
            unlock_modes={"ACCESS_MASTERCLASS": "fully_unlocked"},
            standard_amount=Decimal("6900"),
            final_amount=Decimal("1500"),
            status="active",
            checkout_id=checkout.id,
            created_by="owner",
            telegram_text="test",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add(link)
        db.commit()
        checkout_code = checkout.id.hex
        user_id = user.id

    payload = paid_payload()
    payload.update({
        "orderid": "personal-order-1",
        "paymentid": "personal-payment-1",
        "products": f"EB-{checkout_code} Персональное предложение",
        "price": "1500",
    })
    response = client.post("/integrations/tilda/payments", data=payload, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["access"] == "granted"
    with session_factory() as db:
        assert db.scalar(select(PersonalAccessLink.status)) == "paid"
        assert db.get(User, user_id).access_review_status == "completed"
        assert db.scalar(select(func.count(UserAccess.id))) == 1
        assert db.scalar(select(UserCoursePolicy.unlock_mode)) == "fully_unlocked"
    app.dependency_overrides.clear()
