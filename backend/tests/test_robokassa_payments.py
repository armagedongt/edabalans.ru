import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import quote_plus, unquote_plus

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.intensive_web_access import create_offer_token  # noqa: E402
from app.main import app  # noqa: E402
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
from app.robokassa_service import _result_public_key  # noqa: E402


def certificate_pair(
    encoding: serialization.Encoding = serialization.Encoding.DER,
) -> tuple[rsa.RSAPrivateKey, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "robokassa.test")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    certificate_bytes = certificate.public_bytes(encoding)
    return key, base64.b64encode(certificate_bytes).decode("ascii")


def make_client(
    *, test_mode: bool = True
) -> tuple[TestClient, sessionmaker[Session], rsa.RSAPrivateKey]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    key, certificate = certificate_pair()
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_auth_secret="robokassa-tests",
        allowed_origins="https://похудение-это-есть.рф",
        robokassa_checkout_enabled=True,
        robokassa_test_mode=test_mode,
        robokassa_merchant_login="edabalans-test",
        robokassa_password_1="production-password-1",
        robokassa_test_password_1="test-password-1",
        robokassa_hash_algorithm="sha256",
        robokassa_jws_certificate_base64=certificate,
        robokassa_receipt_tax="none",
    )

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, base_url="https://app.edabalans.ru"), factory, key


def test_official_pem_certificate_format_is_accepted() -> None:
    _, certificate = certificate_pair(serialization.Encoding.PEM)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_auth_secret="robokassa-tests",
        robokassa_jws_certificate_base64=certificate,
    )

    assert isinstance(_result_public_key(settings), rsa.RSAPublicKey)


def seed_catalog(factory: sessionmaker[Session]) -> None:
    with factory() as db:
        product = Product(code="MASTERCLASS_BASIC", name="Минимальный")
        resource = Resource(code="ACCESS_MASTERCLASS", name="Мастер-класс")
        version = PricingVersion(
            version_number=1,
            name="Тестовые цены",
            status="active",
            created_by="test",
            activated_at=datetime.now(timezone.utc),
        )
        db.add_all([product, resource, version])
        db.flush()
        db.add(
            PriceEntry(
                version_id=version.id,
                code="site.masterclass.basic",
                section="site_tariffs",
                name="Минимальный",
                product_code=product.code,
                resource_codes=[resource.code],
                regular_amount=Decimal("6900"),
                compare_at_amount=Decimal("6900"),
                sale_amount=Decimal("5900"),
                enabled=True,
                sort_order=10,
            )
        )
        db.commit()


def signed_result(
    key: rsa.RSAPrivateKey,
    invoice_id: str,
    amount: str,
    *,
    operation_id: str = "operation-1",
    shop: str = "edabalans-test",
    state: str = "OK",
) -> str:
    header = {"typ": "JWT", "alg": "RS256"}
    payload = {
        "header": {
            "type": "PaymentStateNotification",
            "version": "1.0.0",
            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        },
        "data": {
            "shop": shop,
            "opKey": operation_id,
            "invId": invoice_id,
            "paymentMethod": "BankCard",
            "incSum": amount,
            "state": state,
        },
    }

    def encoded(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    signing_input = f"{encoded(header)}.{encoded(payload)}"
    signature = key.sign(
        signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
    )
    return f"{signing_input}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def create_checkout(client: TestClient, *, email: str = "buyer@example.test") -> dict:
    response = client.post(
        "/api/payments/robokassa/checkout",
        json={"price_code": "site.masterclass.basic", "email": email},
        headers={"Origin": "https://app.edabalans.ru"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_checkout_uses_database_price_and_does_not_create_user() -> None:
    client, factory, _ = make_client()
    seed_catalog(factory)
    result = create_checkout(client)

    assert result["amount"] == 5900
    assert result["test_mode"] is True
    fields = result["payment_form"]["fields"]
    assert fields["OutSum"] == "5900.00"
    assert fields["IsTest"] == "1"
    assert fields["ExpirationDate"]
    assert fields["ResultUrl2"].endswith("/integrations/robokassa/result2")
    receipt = json.loads(unquote_plus(fields["Receipt"]))
    assert receipt["items"][0]["sum"] == 5900
    signature_source = ":".join(
        [
            "edabalans-test",
            "5900.00",
            result["invoice_id"],
            fields["Receipt"],
            quote_plus(fields["ResultUrl2"], safe=""),
            quote_plus(fields["SuccessUrl2"], safe=""),
            "GET",
            quote_plus(fields["FailUrl2"], safe=""),
            "GET",
            "test-password-1",
        ]
    )
    assert fields["SignatureValue"] == hashlib.sha256(
        signature_source.encode("utf-8")
    ).hexdigest()
    with factory() as db:
        assert db.scalar(select(func.count(User.id))) == 0
        payment = db.scalar(select(Payment))
        checkout = db.scalar(select(OfferCheckout))
        assert payment is not None and payment.payment_status == "pending"
        assert checkout is not None and checkout.payment_id == payment.id
    app.dependency_overrides.clear()


def test_go_test_page_is_one_button_with_database_price() -> None:
    _, factory, _ = make_client()
    seed_catalog(factory)
    client = TestClient(
        app,
        base_url="https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        client=("go-test-page", 50000),
    )

    response = client.get("/robokassa-test")

    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.text.count("<button") == 1
    assert "Проверить оплату · 5 900 ₽" in response.text
    assert "app.edabalans.ru" not in response.text
    assert 'action="/robokassa-test/start"' in response.text
    app.dependency_overrides.clear()


def test_go_test_button_builds_classic_form_with_go_callbacks() -> None:
    _, factory, _ = make_client()
    seed_catalog(factory)
    client = TestClient(
        app,
        base_url="https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        client=("go-test-start", 50000),
    )

    response = client.post("/robokassa-test/start")

    assert response.status_code == 200
    assert 'action="https://auth.robokassa.ru/Merchant/Index.aspx"' in response.text
    assert 'name="IsTest" value="1"' in response.text
    assert "https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/" in response.text
    assert "app.edabalans.ru" not in response.text
    assert 'document.getElementById("payment").submit()' in response.text
    with factory() as db:
        payment = db.scalar(select(Payment))
        assert payment is not None
        assert payment.amount == Decimal("5900")
        assert payment.payment_status == "pending"
        assert db.scalar(select(func.count(User.id))) == 0
    app.dependency_overrides.clear()


def test_go_test_page_is_disabled_outside_robokassa_test_mode() -> None:
    _, factory, _ = make_client(test_mode=False)
    seed_catalog(factory)
    client = TestClient(
        app,
        base_url="https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        client=("go-test-disabled", 50000),
    )

    assert client.get("/robokassa-test").status_code == 404
    assert client.post("/robokassa-test/start").status_code == 404
    app.dependency_overrides.clear()


def test_go_payment_returns_link_back_to_test_page() -> None:
    _, _, _ = make_client()
    client = TestClient(
        app,
        base_url="https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        client=("go-test-return", 50000),
    )

    success = client.get("/payments/robokassa/success?InvId=123")
    failure = client.get("/payments/robokassa/fail")

    assert 'href="/robokassa-test"' in success.text
    assert 'href="/robokassa-test"' in failure.text
    app.dependency_overrides.clear()


def test_checkout_fails_before_redirect_when_result2_certificate_is_missing() -> None:
    client, factory, _ = make_client()
    seed_catalog(factory)
    current = app.dependency_overrides[get_settings]()
    app.dependency_overrides[get_settings] = lambda: current.model_copy(
        update={"robokassa_jws_certificate_base64": ""}
    )

    response = client.post(
        "/api/payments/robokassa/checkout",
        json={"price_code": "site.masterclass.basic", "email": "buyer@example.test"},
        headers={"Origin": "https://app.edabalans.ru"},
    )

    assert response.status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count(Payment.id))) == 0
    app.dependency_overrides.clear()


def test_signed_test_result_creates_user_without_production_access_and_is_idempotent() -> None:
    client, factory, key = make_client()
    seed_catalog(factory)
    result = create_checkout(client)
    notification = signed_result(key, result["invoice_id"], "5900.00")

    first = client.post("/integrations/robokassa/result2", content=notification)
    second = client.post("/integrations/robokassa/result2", content=notification)

    assert first.status_code == 200
    assert first.text == f"OK{result['invoice_id']}"
    assert second.status_code == 200
    with factory() as db:
        payment = db.scalar(select(Payment))
        checkout = db.scalar(select(OfferCheckout))
        email = db.scalar(select(UserEmail))
        assert payment is not None and payment.payment_status == "test_paid"
        assert payment.external_payment_id == "operation-1"
        assert checkout is not None and checkout.status == "test_paid"
        assert email is not None and email.source == "robokassa"
        assert email.email_normalized == "buyer@example.test"
        assert payment.user_id == email.user_id == checkout.user_id
        assert db.scalar(select(func.count(User.id))) == 1
        assert db.scalar(select(func.count(UserAccess.id))) == 0
    app.dependency_overrides.clear()


def test_signed_production_result_grants_access() -> None:
    client, factory, key = make_client(test_mode=False)
    seed_catalog(factory)
    result = create_checkout(client, email="paid@example.test")

    response = client.post(
        "/integrations/robokassa/result2",
        content=signed_result(key, result["invoice_id"], "5900.00"),
    )

    assert response.status_code == 200
    with factory() as db:
        payment = db.scalar(select(Payment))
        assert payment is not None and payment.payment_status == "paid"
        assert db.scalar(select(func.count(User.id))) == 1
        assert db.scalar(select(func.count(UserAccess.id))) == 1
    app.dependency_overrides.clear()


def test_invalid_signature_or_amount_cannot_confirm_payment() -> None:
    client, factory, key = make_client()
    seed_catalog(factory)
    result = create_checkout(client, email="safe@example.test")
    other_key, _ = certificate_pair()

    invalid = client.post(
        "/integrations/robokassa/result2",
        content=signed_result(other_key, result["invoice_id"], "5900.00"),
    )
    wrong_amount = client.post(
        "/integrations/robokassa/result2",
        content=signed_result(key, result["invoice_id"], "1.00"),
    )

    assert invalid.status_code == 400
    assert wrong_amount.status_code == 400
    with factory() as db:
        payment = db.scalar(select(Payment))
        assert payment is not None and payment.payment_status == "pending"
        assert db.scalar(select(func.count(User.id))) == 0
        assert db.scalar(select(func.count(UserAccess.id))) == 0
    app.dependency_overrides.clear()


def test_signed_wrong_shop_or_non_ok_state_cannot_confirm_payment() -> None:
    client, factory, key = make_client()
    seed_catalog(factory)
    result = create_checkout(client)

    wrong_shop = client.post(
        "/integrations/robokassa/result2",
        content=signed_result(
            key, result["invoice_id"], "5900.00", shop="another-shop"
        ),
    )
    failed_state = client.post(
        "/integrations/robokassa/result2",
        content=signed_result(key, result["invoice_id"], "5900.00", state="FAIL"),
    )

    assert wrong_shop.status_code == 400
    assert failed_state.status_code == 400
    with factory() as db:
        payment = db.scalar(select(Payment))
        assert payment is not None and payment.payment_status == "pending"
        assert db.scalar(select(func.count(User.id))) == 0
    app.dependency_overrides.clear()


def test_personal_offer_changes_preview_and_checkout_by_one_thousand() -> None:
    client, factory, key = make_client()
    seed_catalog(factory)
    with factory() as db:
        user = User(display_name="Избранный", data_origin="native")
        db.add(user)
        db.flush()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
        db.add(
            UserOffer(
                user_id=user.id,
                stage_code="intensive_day4_discount",
                started_at=datetime.now(timezone.utc),
                expires_at=expires_at,
                status="active",
                snapshot={"offer_id": "intensive-day4-1000", "discount_amount": 1000},
            )
        )
        db.commit()
        token = create_offer_token(db, user.id, expires_at)
        db.commit()
        offer_user_id = user.id

    preview = client.get("/api/pricing/site/preview", params={"intensive_offer": token})
    checkout = client.post(
        "/api/payments/robokassa/checkout",
        json={
            "price_code": "site.masterclass.basic",
            "email": "selected@example.test",
            "intensive_offer": token,
        },
        headers={"Origin": "https://app.edabalans.ru"},
    )

    assert preview.status_code == 200
    assert preview.json()["tariffs"][0]["sale_amount"] == 4900
    assert checkout.status_code == 200
    assert checkout.json()["amount"] == 4900
    assert checkout.json()["payment_form"]["fields"]["OutSum"] == "4900.00"
    callback = client.post(
        "/integrations/robokassa/result2",
        content=signed_result(key, checkout.json()["invoice_id"], "4900.00"),
    )
    assert callback.status_code == 200
    with factory() as db:
        payment = db.scalar(select(Payment))
        email = db.scalar(select(UserEmail))
        assert payment is not None and payment.user_id == offer_user_id
        assert payment.payment_status == "test_paid"
        assert email is not None and email.user_id == offer_user_id
        assert email.email_normalized == "selected@example.test"
        assert db.scalar(select(func.count(User.id))) == 1
        assert db.scalar(select(func.count(UserAccess.id))) == 0
    app.dependency_overrides.clear()


def test_personal_offer_rejects_another_email_before_payment() -> None:
    client, factory, _ = make_client()
    seed_catalog(factory)
    with factory() as db:
        user = User(display_name="Избранный", data_origin="native")
        db.add(user)
        db.flush()
        db.add(
            UserEmail(
                user_id=user.id,
                email_original="selected@example.test",
                email_normalized="selected@example.test",
                source="crm",
                verification_status="legacy_unverified",
            )
        )
        expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
        db.add(
            UserOffer(
                user_id=user.id,
                stage_code="intensive_day4_discount",
                started_at=datetime.now(timezone.utc),
                expires_at=expires_at,
                status="active",
                snapshot={"offer_id": "intensive-day4-1000", "discount_amount": 1000},
            )
        )
        db.commit()
        token = create_offer_token(db, user.id, expires_at)
        db.commit()

    response = client.post(
        "/api/payments/robokassa/checkout",
        json={
            "price_code": "site.masterclass.basic",
            "email": "typo@example.test",
            "intensive_offer": token,
        },
        headers={"Origin": "https://app.edabalans.ru"},
    )

    assert response.status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count(Payment.id))) == 0
    app.dependency_overrides.clear()
