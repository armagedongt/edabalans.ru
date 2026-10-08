import os
import json
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.auth import require_admin  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.intensive_web_access import create_offer_token  # noqa: E402
from app.models import (  # noqa: E402
    OfferCheckout,
    Payment,
    PriceEntry,
    PricingVersion,
    Product,
    Resource,
    User,
    UserAccess,
    UserEmail,
    UserOffer,
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
        app_auth_secret="pricing-intensive-test-secret",
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


def pricing_guards(client: TestClient, version_id: str) -> dict:
    catalog = client.get("/admin/api/pricing").json()
    selected = next(version for version in catalog["versions"] if version["id"] == version_id)
    return {"expected_active": catalog["active_revision"], "expected_draft": selected["revision"]}


def publish_pricing(client: TestClient, version_id: str):
    return client.post(f"/admin/api/pricing/versions/{version_id}/publish",
                       json={**pricing_guards(client, version_id), "confirm": True})


def create_pricing_draft(client: TestClient):
    catalog = client.get("/admin/api/pricing").json()
    return client.post("/admin/api/pricing/drafts",
                       json={"expected_active": catalog["active_revision"], "expected_draft": None})


def source_update(source: dict) -> dict:
    return {"name": source["name"], "note": source["note"], "entries": [
        {key: entry[key] for key in ("code", "regular_amount", "compare_at_amount", "sale_amount", "enabled")}
        for entry in source["entries"]]}


def active_with_disabled_original(client, factory):
    initial_id = seed_draft(factory)
    with factory() as db:
        db.add(PriceEntry(version_id=uuid.UUID(initial_id), code="product.disabled", section="products",
            name="Исходный выключенный продукт", resource_codes=["ACCESS_RECIPES"],
            regular_amount=None, compare_at_amount=None, sale_amount=Decimal("0"), enabled=False,
            metadata_json={"original": {"items": [None, False, 0, "untouched"]}}, sort_order=999))
        db.commit()
    result = publish_pricing(client, initial_id)
    assert result.status_code == 200
    return result.json()["version"]


def test_guarded_clone_noop_and_update_preserve_full_pricing_original():
    client, factory = make_client(enabled=True)
    try:
        active = active_with_disabled_original(client, factory)
        draft = create_pricing_draft(client).json()["version"]
        assert draft["base_active"] == active["revision"]
        assert draft["authoring_ready"]
        assert draft["semantic_sha256"] == active["semantic_sha256"]
        source = deepcopy(draft["source"])
        source["entries"][0]["metadata"].pop("_editorial_pricing")
        assert source == active["source"]
        assert source["entries"][0]["enabled"] is False
        assert source["entries"][0]["regular_amount"] is None
        assert source["entries"][0]["sale_amount"] == "0.00"
        body = {**source_update(draft["source"]), **pricing_guards(client, draft["id"])}
        unchanged = client.put(f"/admin/api/pricing/versions/{draft['id']}", json=body)
        assert unchanged.status_code == 200
        assert unchanged.json()["version"]["revision"] == draft["revision"]
        body["entries"][1]["sale_amount"] = "14900.01"
        updated = client.put(f"/admin/api/pricing/versions/{draft['id']}", json=body)
        assert updated.status_code == 200
        assert updated.json()["version"]["version_number"] == draft["version_number"]
        assert updated.json()["version"]["revision"] != draft["revision"]
        assert updated.json()["version"]["base_active"] == active["revision"]
        snapshot = client.get("/admin/api/pricing").json()
        assert client.put(f"/admin/api/pricing/versions/{draft['id']}", json=body).status_code == 409
        assert client.get("/admin/api/pricing").json() == snapshot
        stored_active = next(row for row in snapshot["versions"] if row["status"] == "active")
        assert stored_active["source"] == active["source"]
    finally:
        app.dependency_overrides.clear()


def test_existing_foreign_draft_is_never_adopted_and_create_replay_is_safe():
    client, factory = make_client(enabled=True)
    try:
        active_with_disabled_original(client, factory)
        draft = create_pricing_draft(client).json()["version"]
        before = client.get("/admin/api/pricing").json()
        assert create_pricing_draft(client).status_code == 409
        assert client.get("/admin/api/pricing").json() == before
        assert before["draft_revision"] == draft["revision"]
        assert len(before["versions"]) == 2
    finally:
        app.dependency_overrides.clear()


def test_activation_and_accepted_response_replay_keep_original_history_without_payment():
    client, factory = make_client(enabled=True)
    try:
        active = active_with_disabled_original(client, factory)
        draft = create_pricing_draft(client).json()["version"]
        guards = pricing_guards(client, draft["id"])
        body = source_update(draft["source"])
        body["entries"][1]["sale_amount"] = "14900.01"
        saved = client.put(f"/admin/api/pricing/versions/{draft['id']}", json={**guards, **body})
        assert saved.status_code == 200
        publish_body = {**pricing_guards(client, draft["id"]), "confirm": True}
        accepted = client.post(f"/admin/api/pricing/versions/{draft['id']}/publish", json=publish_body)
        assert accepted.status_code == 200
        assert accepted.json()["live_consumption_enabled"] is True
        assert accepted.json()["version"]["status"] == "active"
        replay = client.post(f"/admin/api/pricing/versions/{draft['id']}/publish", json=publish_body)
        assert replay.status_code == 200
        assert replay.json()["already_active"] is True
        assert replay.json()["version"] == accepted.json()["version"]
        history = client.get("/admin/api/pricing").json()["versions"]
        assert len(history) == 2
        assert sum(version["status"] == "active" for version in history) == 1
        archived = next(version for version in history if version["status"] == "archived")
        assert archived["source"] == active["source"]
        assert archived["revision"] == active["revision"]
        with factory() as db:
            assert db.scalar(select(func.count(Payment.id))) == 0
            assert db.scalar(select(func.count(OfferCheckout.id))) == 0
    finally:
        app.dependency_overrides.clear()


def test_stale_draft_base_is_rejected_even_with_refetched_current_active_revision():
    client, factory = make_client(enabled=True)
    try:
        active = active_with_disabled_original(client, factory)
        draft = create_pricing_draft(client).json()["version"]
        # Simulate an independent controlled catalog publication, outside this draft.
        with factory() as db:
            db.get(PricingVersion, uuid.UUID(active["id"])).status = "archived"
            version = PricingVersion(version_number=3, name="Independent active", status="active", created_by="test")
            db.add(version); db.flush()
            db.add(PriceEntry(version_id=version.id, code="site.masterclass.consult", section="site_tariffs",
                name="Independent", sale_amount=Decimal("12000"), resource_codes=["ACCESS_MASTERCLASS"]))
            db.commit()
        before = client.get("/admin/api/pricing").json()
        fresh = pricing_guards(client, draft["id"])
        assert fresh["expected_active"] != active["revision"]
        assert client.put(f"/admin/api/pricing/versions/{draft['id']}", json={**fresh, **source_update(draft["source"])}).status_code == 409
        assert client.post(f"/admin/api/pricing/versions/{draft['id']}/publish", json={**fresh, "confirm": True}).status_code == 409
        assert client.get("/admin/api/pricing").json() == before
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("case", ["missing_guard", "unknown_system_field", "missing_price", "fraction", "duplicate", "missing_row", "wrong_hash"])
def test_guarded_write_rejects_unsafe_or_stale_input_atomically(case):
    client, factory = make_client(enabled=True)
    try:
        active_with_disabled_original(client, factory)
        draft = create_pricing_draft(client).json()["version"]
        body = {**source_update(draft["source"]), **pricing_guards(client, draft["id"])}
        if case == "missing_guard": del body["expected_active"]
        elif case == "unknown_system_field": body["entries"][0]["resource_codes"] = []
        elif case == "missing_price": del body["entries"][0]["compare_at_amount"]
        elif case == "fraction": body["entries"][1]["sale_amount"] = "100.001"
        elif case == "duplicate": body["entries"].append(deepcopy(body["entries"][0]))
        elif case == "missing_row": body["entries"].pop()
        elif case == "wrong_hash": body["expected_draft"]["sha256"] = "0" * 64
        before = client.get("/admin/api/pricing").json()
        response = client.put(f"/admin/api/pricing/versions/{draft['id']}", json=body)
        assert response.status_code == (409 if case == "wrong_hash" else 422)
        assert client.get("/admin/api/pricing").json() == before
    finally:
        app.dependency_overrides.clear()


def test_semantic_hash_strips_only_valid_provenance_on_the_first_code():
    from app.pricing_service import source_hash
    source = {"schema_version": 1, "name": "Original", "note": None, "entries": [
        {"code": "a", "metadata": {}}, {"code": "b", "metadata": {}}]}
    original_hash = source_hash(source, semantic=True)
    source["entries"][0]["metadata"]["_editorial_pricing"] = {"schema_version": 1, "owner": "platform.commerce", "base_active": None}
    assert source_hash(source, semantic=True) == original_hash
    source["entries"][0]["metadata"]["_editorial_pricing"]["business"] = "must stay original"
    assert source_hash(source, semantic=True) != original_hash
    source["entries"][0]["metadata"].clear()
    source["entries"][1]["metadata"]["_editorial_pricing"] = {"schema_version": 1, "owner": "platform.commerce", "base_active": None}
    assert source_hash(source, semantic=True) != original_hash


def test_existing_admin_enabled_edit_remains_available_under_revision_guards():
    client, factory = make_client(enabled=True)
    try:
        active = active_with_disabled_original(client, factory)
        draft = create_pricing_draft(client).json()["version"]
        body = {**source_update(draft["source"]), **pricing_guards(client, draft["id"])}
        body["entries"][0]["enabled"] = True
        saved = client.put(f"/admin/api/pricing/versions/{draft['id']}", json=body)
        assert saved.status_code == 200
        assert saved.json()["version"]["source"]["entries"][0]["enabled"] is True
        assert saved.json()["version"]["revision"] != draft["revision"]
        assert client.put(f"/admin/api/pricing/versions/{draft['id']}", json=body).status_code == 409
        current = client.get("/admin/api/pricing").json()
        assert next(version for version in current["versions"] if version["status"] == "active")["source"] == active["source"]
    finally:
        app.dependency_overrides.clear()


def update_pricing(client: TestClient, version_id: str, *, json: dict):
    return client.put(f"/admin/api/pricing/versions/{version_id}",
                      json={**json, **pricing_guards(client, version_id)})


def test_draft_is_editable_but_does_not_change_public_prices() -> None:
    client, factory = make_client(enabled=False)
    version_id = seed_draft(factory)

    catalog = client.get("/admin/api/pricing")
    assert catalog.status_code == 200
    assert catalog.json()["live_consumption_enabled"] is False
    assert catalog.json()["versions"][0]["entries"][0]["sale_amount"] == 15900

    update = update_pricing(
        client, version_id,
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
    published = publish_pricing(client, version_id)
    assert published.status_code == 200
    assert published.json()["version"]["status"] == "active"

    rejected = update_pricing(
        client, version_id,
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
    copied = create_pricing_draft(client)
    assert copied.status_code == 200
    assert copied.json()["version"]["version_number"] == 2
    assert copied.json()["version"]["entries"][0]["sale_amount"] == 15900
    copied_id = copied.json()["version"]["id"]
    republished = publish_pricing(client, copied_id)
    assert republished.status_code == 200
    assert republished.json()["version"]["status"] == "active"
    catalog = client.get("/admin/api/pricing")
    assert [row["status"] for row in catalog.json()["versions"]].count("active") == 1
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
    assert publish_pricing(client, publish_id).status_code == 200
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
    assert checkout.json()["cart_command"].startswith("#order:С консультацией · №")
    assert "EB-" not in checkout.json()["cart_command"]
    with factory() as db:
        assert db.scalar(select(func.count(OfferCheckout.id))) == 1
    app.dependency_overrides.clear()


def test_public_checkout_binds_new_tilda_user_and_keeps_pricing_snapshot() -> None:
    client, factory = make_client(enabled=True)
    version_id = seed_draft(factory)
    assert publish_pricing(client, version_id).status_code == 200

    prices = client.get("/api/pricing/site")
    assert prices.status_code == 200
    assert prices.json()["tariffs"][0]["sale_amount"] == 15900
    checkout_response = client.post(
        "/api/pricing/site/checkout",
        json={"price_code": "site.masterclass.consult"},
    )
    assert checkout_response.status_code == 200
    command = checkout_response.json()["cart_command"]
    assert command.startswith("#order:С консультацией · №")
    assert "EB-" not in command
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
    assert publish_pricing(client, version_id).status_code == 200
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


def test_intensive_offer_discounts_checkout_but_binds_access_to_payer_email() -> None:
    client, factory = make_client(enabled=True)
    version_id = seed_draft(factory)
    assert publish_pricing(client, version_id).status_code == 200

    with factory() as db:
        user = User(display_name="Клиент из Telegram", data_origin="native")
        db.add(user)
        db.flush()
        offer = UserOffer(
            user_id=user.id,
            stage_code="intensive_day4_discount",
            started_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
            status="active",
            snapshot={"offer_id": "intensive-day4-1000", "discount_amount": 1000},
        )
        db.add(offer)
        db.commit()
        user_id = user.id
        token = create_offer_token(db, user.id, offer.expires_at)
        second_token = create_offer_token(db, user.id, offer.expires_at)
        db.commit()

    prices = client.get("/api/pricing/site", params={"intensive_offer": token})
    assert prices.status_code == 200
    assert prices.json()["tariffs"][0]["compare_at_amount"] == 17700
    assert prices.json()["tariffs"][0]["sale_amount"] == 15900
    assert prices.json()["tariffs"][0]["personal_sale_amount"] == 14900
    assert prices.json()["intensive_offer"]["discount_amount"] == 1000

    checkout_response = client.post(
        "/api/pricing/site/checkout",
        json={
            "price_code": "site.masterclass.consult",
            "intensive_offer": token,
        },
    )
    assert checkout_response.status_code == 200
    assert checkout_response.json()["amount"] == 14900
    repeated_checkout = client.post(
        "/api/pricing/site/checkout",
        json={
            "price_code": "site.masterclass.consult",
            "intensive_offer": token,
        },
    )
    assert repeated_checkout.status_code == 409
    repeated_with_fresh_link = client.post(
        "/api/pricing/site/checkout",
        json={
            "price_code": "site.masterclass.consult",
            "intensive_offer": second_token,
        },
    )
    assert repeated_with_fresh_link.status_code == 409
    with factory() as db:
        pending_checkout = db.scalar(select(OfferCheckout))
        assert pending_checkout is not None
        pending_checkout.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    renewed_checkout = client.post(
        "/api/pricing/site/checkout",
        json={
            "price_code": "site.masterclass.consult",
            "intensive_offer": token,
        },
    )
    assert renewed_checkout.status_code == 200
    assert renewed_checkout.json()["cart_command"] != checkout_response.json()["cart_command"]
    raw_product = renewed_checkout.json()["cart_command"].split(":", 1)[1].rsplit("=", 1)[0]

    payment_payload = {
        "Name": "Клиент из Telegram",
        "Email": "messenger-buyer@example.test",
        "orderid": "pricing-intensive-order-1",
        "paymentid": "pricing-intensive-payment-1",
        "products": raw_product,
        "price": "14900",
        "Currency": "RUB",
        "Payment status": "Processing",
    }
    processing = client.post(
        "/integrations/tilda/payments",
        data=payment_payload,
        headers={"X-Tilda-Webhook-Token": TOKEN},
    )
    assert processing.status_code == 200
    processing_offer = client.post(
        "/api/pricing/site/checkout",
        json={
            "price_code": "site.masterclass.consult",
            "intensive_offer": token,
        },
    )
    assert processing_offer.status_code == 409
    payment = client.post(
        "/integrations/tilda/payments",
        data={**payment_payload, "Payment status": "Paid"},
        headers={"X-Tilda-Webhook-Token": TOKEN},
    )
    assert payment.status_code == 200
    with factory() as db:
        checkout = db.scalar(select(OfferCheckout))
        stored_payment = db.scalar(select(Payment))
        email = db.scalar(select(UserEmail))
        assert stored_payment is not None
        assert checkout is not None and checkout.user_id == stored_payment.user_id
        assert checkout.offer_code.startswith("intensive-day4-1000:")
        assert stored_payment.user_id != user_id
        assert email is not None and email.user_id == stored_payment.user_id
        assert db.scalar(select(func.count(User.id))) == 2
    used_offer = client.post(
        "/api/pricing/site/checkout",
        json={
            "price_code": "site.masterclass.consult",
            "intensive_offer": token,
        },
    )
    assert used_offer.status_code == 409
    app.dependency_overrides.clear()
