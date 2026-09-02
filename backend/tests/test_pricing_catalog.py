import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.auth import require_admin  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    OfferCheckout,
    Payment,
    PriceEntry,
    PricingVersion,
    Product,
    Resource,
    UserAccess,
)
from app.product_catalog_service import PRODUCT_CATALOG_SEED  # noqa: E402


TOKEN = "pricing-test-token"


def test_owner_approved_recordings_and_consultation_copy_is_exact() -> None:
    products = {
        item["code"]: item for item in PRODUCT_CATALOG_SEED["products"]
    }
    assert products["recordings"] == {
        **products["recordings"],
        "shortName": "Два реальных разбора",
        "fullName": "Два реальных разбора участников Мастер-класса прошлых потоков",
        "descriptor": "Оригиналы дневника и запись всей консультации.",
    }
    assert products["consultation"] == {
        **products["consultation"],
        "shortName": "Индивидуальная консультация",
        "fullName": "Индивидуальная консультация",
        "descriptor": (
            "Разбор дневника питания, определение плана действий и ответы на любые вопросы."
        ),
    }


def make_client(*, enabled: bool) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: "admin@example.test"
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite+pysqlite:///:memory:",
        tilda_webhook_token=TOKEN,
        pricing_catalog_enabled=enabled,
    )
    return TestClient(app), factory


def seed_draft(factory: sessionmaker[Session]) -> str:
    with factory() as db:
        db.add_all(
            [
                Resource(code="ACCESS_MASTERCLASS", name="Мастер-класс"),
                Resource(code="ACCESS_RECIPES", name="Рецепты"),
                Resource(code="ACCESS_CONSULTATION", name="Консультация"),
                Product(code="MASTERCLASS_CONSULT", name="Максимальный тариф"),
            ]
        )
        version = PricingVersion(
            version_number=1,
            name="Стартовый черновик",
            status="draft",
            created_by="test",
        )
        db.add(version)
        db.flush()
        db.add(
            PriceEntry(
                version_id=version.id,
                code="site.masterclass.consult",
                section="site_tariffs",
                name="С консультацией",
                product_code="MASTERCLASS_CONSULT",
                resource_codes=[
                    "ACCESS_MASTERCLASS",
                    "ACCESS_RECIPES",
                    "ACCESS_CONSULTATION",
                ],
                regular_amount=Decimal("17700"),
                compare_at_amount=Decimal("17700"),
                sale_amount=Decimal("15900"),
                enabled=True,
                sort_order=30,
            )
        )
        db.commit()
        return str(version.id)


def test_draft_is_editable_but_does_not_change_public_prices() -> None:
    client, factory = make_client(enabled=False)
    version_id = seed_draft(factory)

    catalog = client.get("/admin/api/pricing")
    assert catalog.status_code == 200
    assert catalog.json()["live_consumption_enabled"] is False
    assert catalog.json()["versions"][0]["entries"][0]["sale_amount"] == 15900

    update = client.put(
        f"/admin/api/pricing/versions/{version_id}",
        json={
            "name": "Цены для нового сайта",
            "note": "Пока выключено",
            "entries": [
                {
                    "code": "site.masterclass.consult",
                    "regular_amount": 17700,
                    "compare_at_amount": 17700,
                    "sale_amount": 14900,
                    "enabled": True,
                }
            ],
        },
    )
    assert update.status_code == 200
    assert update.json()["version"]["entries"][0]["sale_amount"] == 14900
    assert client.get("/api/pricing/site").status_code == 503
    app.dependency_overrides.clear()


def test_product_catalog_keeps_technical_connections_out_of_editor() -> None:
    client, _ = make_client(enabled=False)
    initial = client.get("/admin/api/product-catalog")
    assert initial.status_code == 200
    body = initial.json()
    product = body["active"]["manifest"]["products"][0]
    assert product["code"] == "masterclass"
    assert "marketing" in product
    assert "Главное зерно" in product["marketing"]
    assert "ai" not in product
    assert "resource" not in product
    assert "app" not in product

    edited = deepcopy(body["active"]["manifest"])
    edited["products"][0]["descriptor"] = "Утверждённый владельцем дескрипшн без шаблонного начала."
    saved = client.put(
        "/admin/api/product-catalog",
        json={"expected_version": body["active"]["version"], "payload": edited},
    )
    assert saved.status_code == 200
    assert saved.json()["active"]["manifest"]["products"][0]["descriptor"] == edited["products"][0]["descriptor"]

    empty_descriptor = deepcopy(saved.json()["active"]["manifest"])
    empty_descriptor["products"][0]["descriptor"] = ""
    rejected_empty = client.put(
        "/admin/api/product-catalog",
        json={
            "expected_version": saved.json()["active"]["version"],
            "payload": empty_descriptor,
        },
    )
    assert rejected_empty.status_code == 422

    invalid = deepcopy(saved.json()["active"]["manifest"])
    invalid["products"][0]["code"] = "other"
    rejected = client.put(
        "/admin/api/product-catalog",
        json={"expected_version": saved.json()["active"]["version"], "payload": invalid},
    )
    assert rejected.status_code == 422
    app.dependency_overrides.clear()


def test_published_version_is_immutable_and_new_draft_is_a_copy() -> None:
    client, factory = make_client(enabled=False)
    version_id = seed_draft(factory)
    published = client.post(f"/admin/api/pricing/versions/{version_id}/publish")
    assert published.status_code == 200
    assert published.json()["version"]["status"] == "active"

    rejected = client.put(
        f"/admin/api/pricing/versions/{version_id}",
        json={
            "name": "Нельзя поменять",
            "entries": [
                {
                    "code": "site.masterclass.consult",
                    "regular_amount": 17700,
                    "compare_at_amount": 17700,
                    "sale_amount": 1,
                    "enabled": True,
                }
            ],
        },
    )
    assert rejected.status_code == 409
    copied = client.post("/admin/api/pricing/drafts")
    assert copied.status_code == 200
    assert copied.json()["version"]["version_number"] == 2
    assert copied.json()["version"]["entries"][0]["sale_amount"] == 15900
    app.dependency_overrides.clear()


def test_preview_reads_prices_and_preview_checkout_requires_published_version() -> None:
    client, factory = make_client(enabled=False)
    seed_draft(factory)

    preview = client.get("/api/pricing/site/preview")
    assert preview.status_code == 200
    assert preview.json()["tariffs"][0]["sale_amount"] == 15900
    assert client.get("/api/pricing/site").status_code == 503
    assert client.post(
        "/api/pricing/site/checkout",
        json={"price_code": "site.masterclass.consult"},
    ).status_code == 503
    assert client.post(
        "/api/pricing/site/preview-checkout",
        json={"price_code": "site.masterclass.consult"},
        headers={"Origin": "http://testserver"},
    ).status_code == 503

    version_id = preview.json()["version"]
    with factory() as db:
        version = db.scalar(select(PricingVersion).where(PricingVersion.version_number == version_id))
        assert version is not None
        publish_id = str(version.id)
    assert client.post(f"/admin/api/pricing/versions/{publish_id}/publish").status_code == 200
    assert "/api/pricing/site/preview-checkout" not in client.get("/openapi.json").json()["paths"]
    with factory() as db:
        db.add(
            OfferCheckout(
                user_id=None,
                checkout_kind="public_site",
                pricing_version_id=version.id,
                price_entry_code="site.masterclass.consult",
                offer_code="site.masterclass.consult",
                title="Просроченный checkout",
                items=[],
                amount=Decimal("15900"),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        db.commit()
    assert client.post(
        "/api/pricing/site/preview-checkout",
        json={"price_code": "site.masterclass.consult"},
    ).status_code == 403
    assert client.post(
        "/api/pricing/site/preview-checkout",
        json={"price_code": "site.masterclass.consult"},
        headers={"Origin": "https://example.test"},
    ).status_code == 403
    checkout = client.post(
        "/api/pricing/site/preview-checkout",
        json={"price_code": "site.masterclass.consult"},
        headers={"Origin": "http://testserver"},
    )
    assert checkout.status_code == 200
    assert checkout.json()["pricing_version"] == version_id
    assert checkout.json()["cart_command"].startswith("#order:EB-")
    with factory() as db:
        assert db.scalar(select(func.count(OfferCheckout.id))) == 1
    app.dependency_overrides.clear()


def test_public_checkout_binds_new_tilda_user_and_keeps_pricing_snapshot() -> None:
    client, factory = make_client(enabled=True)
    version_id = seed_draft(factory)
    assert client.post(f"/admin/api/pricing/versions/{version_id}/publish").status_code == 200

    prices = client.get("/api/pricing/site")
    assert prices.status_code == 200
    assert prices.json()["tariffs"][0]["sale_amount"] == 15900
    checkout_response = client.post(
        "/api/pricing/site/checkout",
        json={"price_code": "site.masterclass.consult"},
    )
    assert checkout_response.status_code == 200
    command = checkout_response.json()["cart_command"]
    assert command.startswith("#order:EB-")
    assert " С консультацией=" in command
    raw_product = command.split(":", 1)[1].rsplit("=", 1)[0]

    payment = client.post(
        "/integrations/tilda/payments",
        data={
            "Name": "Новый клиент",
            "Email": "new@example.test",
            "orderid": "pricing-order-1",
            "paymentid": "pricing-payment-1",
            "products": raw_product,
            "price": "15900",
            "Currency": "RUB",
            "Payment status": "Paid",
            "sent": "2026-08-23 20:00:00",
        },
        headers={"X-Tilda-Webhook-Token": TOKEN},
    )
    assert payment.status_code == 200
    assert payment.json()["access"] == "granted"
    with factory() as db:
        stored = db.scalar(select(Payment))
        assert stored is not None
        assert str(stored.pricing_version_id) == version_id
        assert stored.price_entry_code == "site.masterclass.consult"
        assert stored.product_id is not None
        assert db.scalar(select(func.count(UserAccess.id))) == 3
        checkout = db.scalar(select(OfferCheckout))
        assert checkout is not None
        assert checkout.checkout_kind == "public_site"
        assert checkout.user_id == stored.user_id
        assert checkout.status == "paid"
    app.dependency_overrides.clear()


def test_public_checkout_rejects_tampered_amount_without_creating_payment() -> None:
    client, factory = make_client(enabled=True)
    version_id = seed_draft(factory)
    assert client.post(f"/admin/api/pricing/versions/{version_id}/publish").status_code == 200
    checkout_response = client.post(
        "/api/pricing/site/checkout",
        json={"price_code": "site.masterclass.consult"},
    )
    raw_product = checkout_response.json()["cart_command"].split(":", 1)[1].rsplit("=", 1)[0]

    response = client.post(
        "/integrations/tilda/payments",
        data={
            "Email": "tampered@example.test",
            "orderid": "pricing-order-tampered",
            "paymentid": "pricing-payment-tampered",
            "products": raw_product,
            "price": "1",
            "Currency": "RUB",
            "Payment status": "Paid",
        },
        headers={"X-Tilda-Webhook-Token": TOKEN},
    )
    assert response.status_code == 422
    assert "price does not match" in response.json()["detail"]
    with factory() as db:
        assert db.scalar(select(func.count(Payment.id))) == 0
        assert db.scalar(select(func.count(UserAccess.id))) == 0
    app.dependency_overrides.clear()
