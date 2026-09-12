import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs, unquote_plus, urlsplit

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
from app.account_security import token_hash  # noqa: E402
from app.account_auth_routes import COOKIE_NAME  # noqa: E402
from app.main import app  # noqa: E402
from app.pricing_routes import _preview_checkout_rate_lock, _preview_checkout_rate_state  # noqa: E402
from app.models import (  # noqa: E402
    AccountCredential,
    AccountSession,
    AccountOnboarding,
    MessengerLinkToken,
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
    RecurringSubscription,
)
from app.robokassa_service import _result_public_key  # noqa: E402
import app.robokassa_subscription_service as subscription_service  # noqa: E402


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
    *,
    test_mode: bool = True,
    live_probe_enabled: bool = False,
    account_onboarding_enabled: bool = False,
) -> tuple[TestClient, sessionmaker[Session], rsa.RSAPrivateKey]:
    with _preview_checkout_rate_lock:
        _preview_checkout_rate_state.clear()
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
        account_onboarding_enabled=account_onboarding_enabled,
        robokassa_checkout_enabled=True,
        robokassa_live_probe_enabled=live_probe_enabled,
        robokassa_test_mode=test_mode,
        robokassa_merchant_login="edabalans-test",
        robokassa_password_1="production-password-1",
        robokassa_password_2="production-password-2",
        robokassa_test_password_1="test-password-1",
        robokassa_recurring_worker_enabled=True,
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


def seed_subscription_catalog(
    factory: sessionmaker[Session], *, with_user: bool = True
) -> uuid.UUID | None:
    seed_catalog(factory)
    with factory() as db:
        version = db.scalar(select(PricingVersion).where(PricingVersion.status == "active"))
        db.add(
            PriceEntry(
                version_id=version.id,
                code="subscription.coaching.monthly",
                section="subscriptions",
                name="Индивидуальное сопровождение — 1 месяц",
                product_code="COACHING",
                resource_codes=[],
                regular_amount=Decimal("9800"),
                compare_at_amount=Decimal("9800"),
                sale_amount=Decimal("9800"),
                enabled=True,
                sort_order=10,
            )
        )
        if not with_user:
            db.commit()
            return None
        user = User(display_name="Участник", data_origin="native")
        db.add(user)
        db.flush()
        db.add_all(
            [UserEmail(
                user_id=user.id,
                email_original="member@example.test",
                email_normalized="member@example.test",
                source="test",
                verification_status="verified",
            ),
            AccountCredential(
                user_id=user.id,
                password_hash="not-used-in-subscription-test",
                password_version=1,
                issued_via="test",
            )]
        )
        db.commit()
        return user.id


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
    assert fields["Receipt"].startswith("%7B")
    signature_source = ":".join(
        [
            "edabalans-test",
            "5900.00",
            result["invoice_id"],
            fields["Receipt"],
            fields["ResultUrl2"],
            fields["SuccessUrl2"],
            "GET",
            fields["FailUrl2"],
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


def test_go_test_button_redirects_to_classic_interface_with_go_callbacks() -> None:
    _, factory, _ = make_client()
    seed_catalog(factory)
    client = TestClient(
        app,
        base_url="https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        client=("go-test-start", 50000),
    )

    response = client.post("/robokassa-test/start", follow_redirects=False)

    assert response.status_code == 303
    location = response.headers["location"]
    parsed = urlsplit(location)
    fields = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://auth.robokassa.ru/Merchant/Index.aspx"
    )
    assert fields["IsTest"] == ["1"]
    assert json.loads(unquote_plus(fields["Receipt"][0]))["items"][0]["sum"] == 5900
    assert fields["ResultUrl2"][0].startswith(
        "https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/"
    )
    assert "app.edabalans.ru" not in location
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


def test_go_payment_returns_link_back_only_after_failed_payment() -> None:
    _, _, _ = make_client()
    client = TestClient(
        app,
        base_url="https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        client=("go-test-return", 50000),
    )

    success = client.get("/payments/robokassa/success?InvId=123")
    failure = client.get("/payments/robokassa/fail")

    assert 'href="/robokassa-test"' not in success.text
    assert 'href="/robokassa-test"' in failure.text
    app.dependency_overrides.clear()


def test_public_payment_success_waits_for_callback_then_renders_canonical_copy() -> None:
    _, _, _ = make_client(account_onboarding_enabled=True)
    client = TestClient(app, base_url="https://app.edabalans.ru")

    response = client.get("/payments/robokassa/success?InvId=123")

    assert response.status_code == 200
    assert "Проверьте почту, на которую оформляли заказ" in response.text
    assert "Туда отправлен чек о покупке" in response.text
    assert "const successContent=" in response.text
    assert 'href="/preview/homepage-release-candidate#pricing"' not in response.text
    app.dependency_overrides.clear()


def test_public_payment_success_copy_does_not_depend_on_onboarding_feature_flag() -> None:
    _, _, _ = make_client(account_onboarding_enabled=False)
    client = TestClient(app, base_url="https://app.edabalans.ru")

    response = client.get("/payments/robokassa/success?InvId=123")

    assert response.status_code == 200
    assert "данные для входа в личный кабинет и ссылка на него" in response.text
    app.dependency_overrides.clear()


def test_public_payment_success_preview_shows_final_paid_state() -> None:
    client = TestClient(app, base_url="https://app.edabalans.ru")

    response = client.get("/preview/robokassa-success")

    assert response.status_code == 200
    assert "Оплата прошла успешно" in response.text
    assert "данные для входа в личный кабинет и ссылка на него" in response.text
    assert "Туда отправлен чек о покупке" in response.text
    assert "text-align:left" in response.text
    assert 'href="/preview/homepage-release-candidate#pricing"' not in response.text


def test_manual_service_success_preview_has_contacts_and_receipt() -> None:
    client = TestClient(app, base_url="https://app.edabalans.ru")

    response = client.get("/preview/robokassa-success/manual-service")

    assert response.status_code == 200
    assert "Чек о покупке отправлен вам на почту" in response.text
    assert "Мне тоже придёт уведомление об оплате" in response.text
    assert "https://t.me/FitnessSergey" in response.text
    assert 'Вернуться на сайт' not in response.text


def test_member_offer_success_preview_links_account_and_contacts() -> None:
    client = TestClient(app, base_url="https://app.edabalans.ru")

    response = client.get("/preview/robokassa-success/member-offer")

    assert response.status_code == 200
    assert 'href="/lk">личном кабинете</a>' in response.text
    assert "Чек о покупке отправлен вам на почту" in response.text
    assert "хотите уточнить сроки" in response.text


def test_live_probe_page_is_explicitly_enabled_and_noindex() -> None:
    _, _, _ = make_client(live_probe_enabled=True)
    client = TestClient(
        app,
        base_url="https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        client=("go-live-probe-page", 50000),
    )

    response = client.get("/robokassa-live-probe")

    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "Реальная оплата 10 ₽" in response.text
    assert 'action="/robokassa-live-probe/start"' in response.text
    assert 'name="email"' in response.text
    app.dependency_overrides.clear()


def test_live_probe_is_hidden_when_disabled() -> None:
    _, _, _ = make_client(live_probe_enabled=False)
    client = TestClient(
        app,
        base_url="https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        client=("go-live-probe-disabled", 50000),
    )

    assert client.get("/robokassa-live-probe").status_code == 404
    assert (
        client.post(
            "/robokassa-live-probe/start",
            data={"email": "owner@example.test"},
            headers={"Origin": "https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai"},
        ).status_code
        == 404
    )
    app.dependency_overrides.clear()


def test_live_probe_creates_real_ten_ruble_invoice_with_production_password() -> None:
    _, factory, _ = make_client(live_probe_enabled=True)
    client = TestClient(
        app,
        base_url="https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        client=("go-live-probe-start", 50000),
    )

    response = client.post(
        "/robokassa-live-probe/start",
        data={
            "email": "owner@example.test",
            "amount": "99999.99",
            "price_code": "site.masterclass.consultation",
        },
        headers={"Origin": "https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    parsed = urlsplit(response.headers["location"])
    fields = parse_qs(parsed.query)
    assert fields["OutSum"] == ["10.00"]
    assert fields["IsTest"] == ["0"]
    assert fields["ResultUrl2"] == [
        "https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/integrations/robokassa/result2"
    ]
    assert fields["SuccessUrl2"] == [
        "https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/payments/robokassa/live-probe-success"
    ]
    receipt = json.loads(unquote_plus(fields["Receipt"][0]))
    assert receipt["items"][0]["sum"] == 10
    signature_source = ":".join(
        [
            "edabalans-test",
            "10.00",
            fields["InvId"][0],
            fields["Receipt"][0],
            fields["ResultUrl2"][0],
            fields["SuccessUrl2"][0],
            "GET",
            fields["FailUrl2"][0],
            "GET",
            "production-password-1",
        ]
    )
    assert fields["SignatureValue"] == [
        hashlib.sha256(signature_source.encode("utf-8")).hexdigest()
    ]
    with factory() as db:
        payment = db.scalar(select(Payment))
        checkout = db.scalar(select(OfferCheckout))
        assert payment is not None and payment.amount == Decimal("10.00")
        assert payment.raw_payload["live_probe"] is True
        assert checkout is not None and checkout.checkout_kind == "robokassa_live_probe"
        assert checkout.items == []
        assert db.scalar(select(func.count(User.id))) == 0
    app.dependency_overrides.clear()


def test_live_probe_result_records_payment_without_user_access_or_onboarding() -> None:
    _, factory, key = make_client(
        live_probe_enabled=True,
        account_onboarding_enabled=True,
    )
    client = TestClient(
        app,
        base_url="https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        client=("go-live-probe-result", 50000),
    )
    start = client.post(
        "/robokassa-live-probe/start",
        data={"email": "owner@example.test"},
        headers={"Origin": "https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai"},
        follow_redirects=False,
    )
    invoice_id = parse_qs(urlsplit(start.headers["location"]).query)["InvId"][0]
    notification = signed_result(key, invoice_id, "10.00", operation_id="live-operation")

    first = client.post("/integrations/robokassa/result2", content=notification)
    second = client.post("/integrations/robokassa/result2", content=notification)

    assert first.status_code == 200
    assert first.text == f"OK{invoice_id}"
    assert second.status_code == 200
    assert second.text == f"OK{invoice_id}"
    assert client.get(f"/api/payments/robokassa/{invoice_id}/status").json()["status"] == "paid"
    with factory() as db:
        payment = db.scalar(select(Payment))
        checkout = db.scalar(select(OfferCheckout))
        assert payment is not None and payment.payment_status == "paid"
        assert payment.user_id is None
        assert payment.raw_payload["integration"]["live_probe"] is True
        assert checkout is not None and checkout.status == "paid"
        assert checkout.user_id is None
        assert db.scalar(select(func.count(User.id))) == 0
        assert db.scalar(select(func.count(UserAccess.id))) == 0
        assert db.scalar(select(func.count(AccountOnboarding.id))) == 0
        assert db.scalar(select(func.count(AccountCredential.user_id))) == 0
        assert db.scalar(select(func.count(MessengerLinkToken.id))) == 0
    app.dependency_overrides.clear()


def test_live_probe_rejects_wrong_host_and_cross_origin_requests() -> None:
    _, factory, _ = make_client(live_probe_enabled=True)
    app_client = TestClient(
        app,
        base_url="https://app.edabalans.ru",
        client=("live-probe-wrong-host", 50000),
    )
    go_client = TestClient(
        app,
        base_url="https://go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
        client=("live-probe-cross-origin", 50000),
    )

    assert app_client.get("/robokassa-live-probe").status_code == 404
    assert (
        app_client.post(
            "/robokassa-live-probe/start",
            data={"email": "owner@example.test"},
            headers={"Origin": "https://app.edabalans.ru"},
        ).status_code
        == 404
    )
    assert (
        go_client.post(
            "/robokassa-live-probe/start",
            data={"email": "owner@example.test"},
            headers={"Origin": "https://attacker.example"},
        ).status_code
        == 403
    )
    assert (
        go_client.post(
            "/robokassa-live-probe/start",
            data={"email": "owner@example.test"},
        ).status_code
        == 403
    )
    with factory() as db:
        assert db.scalar(select(func.count(Payment.id))) == 0
        assert db.scalar(select(func.count(OfferCheckout.id))) == 0
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
    status_response = client.get(f"/api/payments/robokassa/{result['invoice_id']}/status")
    assert status_response.json()["success_kind"] == "public_masterclass"
    with factory() as db:
        payment = db.scalar(select(Payment))
        assert payment is not None and payment.payment_status == "paid"
        assert payment.raw_payload["success_kind"] == "public_masterclass"
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
    assert preview.json()["tariffs"][0]["sale_amount"] == 5900
    assert preview.json()["tariffs"][0]["personal_sale_amount"] == 4900
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


def test_manual_payment_keeps_comment_without_creating_access_or_account() -> None:
    client, factory, key = make_client()

    page = client.get("/pay")
    checkout = client.post(
        "/api/payments/robokassa/manual-checkout",
        json={
            "amount": "3500.50",
            "payer_name": "Ирина Петрова",
            "email": "irina@example.test",
            "comment": "Консультация по питанию, о которой договорились",
        },
        headers={"Origin": "https://app.edabalans.ru"},
    )

    assert page.status_code == 200
    assert "Страница индивидуальной оплаты" in page.text
    assert "Укажите сумму в рублях" in page.text
    assert 'value="9 900"' not in page.text
    assert 'id="details-modal"' not in page.text
    assert "history.pushState" in page.text
    assert 'class="legal"><input' in page.text
    assert checkout.status_code == 200
    assert checkout.json()["amount"] == 3500.5
    assert checkout.json()["payment_form"]["fields"]["OutSum"] == "3500.50"
    callback = client.post(
        "/integrations/robokassa/result2",
        content=signed_result(key, checkout.json()["invoice_id"], "3500.50"),
    )
    assert callback.status_code == 200
    with factory() as db:
        payment = db.scalar(select(Payment))
        checkout_row = db.scalar(select(OfferCheckout))
        assert payment is not None
        assert payment.payment_status == "test_paid"
        assert payment.raw_payload["payer_name"] == "Ирина Петрова"
        assert payment.raw_payload["comment"] == "Консультация по питанию, о которой договорились"
        assert checkout_row is not None and checkout_row.checkout_kind == "manual_service"
        assert db.scalar(select(func.count(User.id))) == 0
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


def test_public_subscription_uses_postgres_price_and_existing_account() -> None:
    client, factory, _ = make_client()
    user_id = seed_subscription_catalog(factory)

    page = client.get("/subscription")
    offer = client.get("/api/payments/robokassa/subscription/offer")
    checkout = client.post(
        "/api/payments/robokassa/subscription/checkout",
        json={"email": "member@example.test", "accept_terms": True},
        headers={"Origin": "https://app.edabalans.ru"},
    )

    assert page.status_code == 200
    assert "Управление подпиской" in page.text
    assert offer.status_code == 200
    assert offer.json()["amount"] == 9800
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["amount"] == 9800
    fields = checkout.json()["payment_form"]["fields"]
    assert fields["OutSum"] == "9800.00"
    assert fields["Recurring"] == "true"
    with factory() as db:
        row = db.scalar(select(RecurringSubscription))
        payment = db.scalar(select(Payment))
        assert row is not None and row.user_id == user_id
        assert row.amount == Decimal("9800")
        assert payment is not None and payment.user_id == user_id
        assert db.scalar(select(func.count(User.id))) == 1
    app.dependency_overrides.clear()


def test_subscription_month_end_is_clamped_to_last_calendar_day() -> None:
    january = datetime(2027, 1, 31, 12, 30, tzinfo=timezone.utc)
    leap_january = datetime(2028, 1, 31, 12, 30, tzinfo=timezone.utc)

    assert subscription_service.add_calendar_month(january) == datetime(
        2027, 2, 28, 12, 30, tzinfo=timezone.utc
    )
    assert subscription_service.add_calendar_month(leap_january) == datetime(
        2028, 2, 29, 12, 30, tzinfo=timezone.utc
    )


def test_subscription_rejects_unknown_account_before_creating_invoice() -> None:
    client, factory, _ = make_client()
    seed_subscription_catalog(factory, with_user=False)

    response = client.post(
        "/api/payments/robokassa/subscription/checkout",
        json={"email": "unknown@example.test", "accept_terms": True},
        headers={"Origin": "https://app.edabalans.ru"},
    )

    assert response.status_code == 422
    assert "Не удалось подтвердить готовый аккаунт" in response.text
    with factory() as db:
        assert db.scalar(select(func.count(Payment.id))) == 0
        assert db.scalar(select(func.count(RecurringSubscription.id))) == 0
    app.dependency_overrides.clear()


def test_subscription_result_activates_month_without_account_onboarding() -> None:
    client, factory, key = make_client(
        test_mode=False, account_onboarding_enabled=True
    )
    user_id = seed_subscription_catalog(factory)
    checkout = client.post(
        "/api/payments/robokassa/subscription/checkout",
        json={"email": "member@example.test", "accept_terms": True},
        headers={"Origin": "https://app.edabalans.ru"},
    ).json()

    response = client.post(
        "/integrations/robokassa/result2",
        content=signed_result(key, checkout["invoice_id"], "9800.00"),
    )

    assert response.status_code == 200, response.text
    status_response = client.get(
        f"/api/payments/robokassa/{checkout['invoice_id']}/status"
    )
    assert status_response.json()["success_kind"] == "coaching_subscription"
    with factory() as db:
        row = db.scalar(select(RecurringSubscription))
        assert row is not None and row.status == "active"
        assert row.user_id == user_id
        assert row.successful_payments == 1
        assert row.current_period_end == subscription_service.add_calendar_month(
            row.current_period_start
        )
        assert row.next_charge_at == row.current_period_end
        assert db.scalar(select(func.count(User.id))) == 1
        assert db.scalar(select(func.count(AccountOnboarding.id))) == 0
    app.dependency_overrides.clear()


def test_subscription_cancellation_requires_login_and_stops_future_charge() -> None:
    client, factory, key = make_client(test_mode=False)
    user_id = seed_subscription_catalog(factory)
    checkout = client.post(
        "/api/payments/robokassa/subscription/checkout",
        json={"email": "member@example.test", "accept_terms": True},
        headers={"Origin": "https://app.edabalans.ru"},
    ).json()
    client.post(
        "/integrations/robokassa/result2",
        content=signed_result(key, checkout["invoice_id"], "9800.00"),
    )

    denied = client.post(
        "/api/payments/robokassa/subscription/cancel",
        headers={"Origin": "https://app.edabalans.ru"},
    )
    assert denied.status_code == 401
    raw_session = "subscription-session-token"
    with factory() as db:
        db.add(
            AccountSession(
                user_id=user_id,
                token_hash=token_hash(raw_session),
                password_version=1,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                last_seen_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    client.cookies.set(COOKIE_NAME, raw_session)

    cancelled = client.post(
        "/api/payments/robokassa/subscription/cancel",
        headers={"Origin": "https://app.edabalans.ru"},
    )

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["subscription"]["status"] == "cancelled"
    with factory() as db:
        row = db.scalar(select(RecurringSubscription))
        assert row is not None and row.next_charge_at is None
        assert row.current_period_end is not None
    app.dependency_overrides.clear()


def test_failed_recurring_charge_notifies_only_after_final_failure(monkeypatch) -> None:
    _, factory, _ = make_client(test_mode=False)
    user_id = seed_subscription_catalog(factory)
    now = datetime.now(timezone.utc)
    with factory() as db:
        version = db.scalar(select(PricingVersion).where(PricingVersion.status == "active"))
        subscription = RecurringSubscription(
            user_id=user_id,
            product_code="COACHING",
            price_entry_code="subscription.coaching.monthly",
            pricing_version_id=version.id,
            email_normalized="member@example.test",
            amount=Decimal("9800"),
            status="charging",
            parent_invoice_id="100",
            pending_invoice_id="101",
            current_period_start=now - timedelta(days=31),
            current_period_end=now,
            next_status_check_at=now,
            terms_accepted_at=now - timedelta(days=31),
        )
        payment = Payment(
            user_id=user_id,
            source="robokassa",
            external_order_id="101",
            email_at_purchase="member@example.test",
            product_name_raw="Индивидуальное сопровождение — 1 месяц",
            amount=Decimal("9800"),
            payment_status="pending",
        )
        db.add(payment)
        db.flush()
        db.add(
            OfferCheckout(
                user_id=user_id,
                checkout_kind="recurring_subscription",
                offer_code="subscription.coaching.monthly",
                title="Индивидуальное сопровождение — 1 месяц",
                items=[],
                amount=Decimal("9800"),
                expires_at=now + timedelta(days=1),
                payment_id=payment.id,
            )
        )
        db.add(subscription)
        db.commit()

    settings = app.dependency_overrides[get_settings]().model_copy(
        update={
            "robokassa_password_2": "production-password-2",
            "smtp_host": "smtp.example.test",
            "smtp_from_email": "hello@example.test",
        }
    )
    monkeypatch.setattr(subscription_service, "SessionLocal", factory)
    monkeypatch.setattr(
        subscription_service,
        "_operation_state",
        lambda _settings, _invoice: (0, 10),
    )
    sent = []
    monkeypatch.setattr(
        subscription_service,
        "_send_message",
        lambda message, _settings: sent.append(message),
    )

    assert subscription_service.send_one_failure_notification(settings) is False
    assert subscription_service.check_one_pending_charge(settings) is True
    assert sent == []
    assert subscription_service.send_one_failure_notification(settings) is True
    assert len(sent) == 1
    assert "пополните" in sent[0].get_body(preferencelist=("plain",)).get_content().lower()
    assert subscription_service.send_one_failure_notification(settings) is False
    with factory() as db:
        row = db.scalar(select(RecurringSubscription))
        assert row is not None and row.status == "past_due"
        assert row.failure_notification_status == "sent"
        assert row.failure_notified_at is not None
    app.dependency_overrides.clear()


def test_due_subscription_creates_child_invoice_on_recurring_endpoint(monkeypatch) -> None:
    _, factory, _ = make_client(test_mode=False)
    user_id = seed_subscription_catalog(factory)
    now = datetime.now(timezone.utc)
    with factory() as db:
        version = db.scalar(select(PricingVersion).where(PricingVersion.status == "active"))
        db.add(
            RecurringSubscription(
                user_id=user_id,
                product_code="COACHING",
                price_entry_code="subscription.coaching.monthly",
                pricing_version_id=version.id,
                email_normalized="member@example.test",
                amount=Decimal("9800"),
                status="active",
                parent_invoice_id="100",
                successful_payments=1,
                current_period_start=now - timedelta(days=31),
                current_period_end=now,
                next_charge_at=now,
                terms_accepted_at=now - timedelta(days=31),
            )
        )
        db.commit()

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return f"OK+{captured['fields']['InvoiceID']}".encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["fields"] = {
            key: values[0]
            for key, values in parse_qs(request.data.decode()).items()
        }
        return FakeResponse()

    monkeypatch.setattr(subscription_service, "SessionLocal", factory)
    monkeypatch.setattr(subscription_service.urllib.request, "urlopen", fake_urlopen)
    settings = app.dependency_overrides[get_settings]().model_copy(
        update={"robokassa_result_url_2": "https://edabalans.ru/integrations/robokassa/result2"}
    )

    assert subscription_service.charge_one_due_subscription(settings) is True
    fields = captured["fields"]
    assert captured["url"] == "https://auth.robokassa.ru/Merchant/Recurring"
    assert fields["PreviousInvoiceID"] == "100"
    assert fields["OutSum"] == "9800.00"
    assert "Recurring" not in fields
    signature_source = ":".join(
        [
            "edabalans-test",
            "9800.00",
            fields["InvoiceID"],
            fields["Receipt"],
            fields["ResultUrl2"],
            "production-password-1",
        ]
    )
    assert fields["SignatureValue"] == hashlib.sha256(
        signature_source.encode("utf-8")
    ).hexdigest()
    with factory() as db:
        row = db.scalar(select(RecurringSubscription))
        child = db.scalar(
            select(Payment).where(Payment.external_order_id == fields["InvoiceID"])
        )
        assert row is not None and row.status == "charging"
        assert row.pending_invoice_id == fields["InvoiceID"]
        assert row.next_status_check_at is not None
        assert child is not None and child.raw_payload["recurring_role"] == "child"
    app.dependency_overrides.clear()


def test_lost_recurring_response_is_polled_before_failure_email(monkeypatch) -> None:
    _, factory, _ = make_client(test_mode=False)
    user_id = seed_subscription_catalog(factory)
    now = datetime.now(timezone.utc)
    with factory() as db:
        version = db.scalar(select(PricingVersion).where(PricingVersion.status == "active"))
        db.add(
            RecurringSubscription(
                user_id=user_id,
                product_code="COACHING",
                price_entry_code="subscription.coaching.monthly",
                pricing_version_id=version.id,
                email_normalized="member@example.test",
                amount=Decimal("9800"),
                status="active",
                parent_invoice_id="100",
                successful_payments=1,
                current_period_start=now - timedelta(days=31),
                current_period_end=now,
                next_charge_at=now,
                terms_accepted_at=now - timedelta(days=31),
            )
        )
        db.commit()

    monkeypatch.setattr(subscription_service, "SessionLocal", factory)
    monkeypatch.setattr(
        subscription_service.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("response lost")),
    )
    settings = app.dependency_overrides[get_settings]()

    assert subscription_service.charge_one_due_subscription(settings) is True
    with factory() as db:
        row = db.scalar(select(RecurringSubscription))
        assert row is not None and row.status == "charging"
        assert row.pending_invoice_id is not None
        assert row.next_status_check_at is not None
        assert row.failure_notification_status is None
    app.dependency_overrides.clear()


def test_operation_state_recovers_success_when_result2_is_delayed(monkeypatch) -> None:
    _, factory, _ = make_client(test_mode=False)
    user_id = seed_subscription_catalog(factory)
    now = datetime.now(timezone.utc)
    with factory() as db:
        version = db.scalar(select(PricingVersion).where(PricingVersion.status == "active"))
        subscription = RecurringSubscription(
            user_id=user_id,
            product_code="COACHING",
            price_entry_code="subscription.coaching.monthly",
            pricing_version_id=version.id,
            email_normalized="member@example.test",
            amount=Decimal("9800"),
            status="charging",
            parent_invoice_id="100",
            pending_invoice_id="101",
            successful_payments=1,
            current_period_start=now - timedelta(days=31),
            current_period_end=now,
            charge_started_at=now - timedelta(minutes=10),
            next_status_check_at=now,
            terms_accepted_at=now - timedelta(days=31),
        )
        db.add(subscription)
        db.flush()
        payment = Payment(
            user_id=user_id,
            pricing_version_id=version.id,
            price_entry_code="subscription.coaching.monthly",
            source="robokassa",
            external_order_id="101",
            email_at_purchase="member@example.test",
            product_name_raw="Индивидуальное сопровождение — 1 месяц",
            amount=Decimal("9800"),
            payment_status="pending",
            raw_payload={
                "subscription_id": str(subscription.id),
                "recurring_role": "child",
                "account_purchase": True,
            },
        )
        db.add(payment)
        db.flush()
        db.add(
            OfferCheckout(
                user_id=user_id,
                checkout_kind="recurring_subscription",
                offer_code="subscription.coaching.monthly",
                title="Индивидуальное сопровождение — 1 месяц",
                items=[],
                amount=Decimal("9800"),
                expires_at=now + timedelta(days=1),
                payment_id=payment.id,
            )
        )
        db.commit()

    settings = app.dependency_overrides[get_settings]().model_copy(
        update={"robokassa_password_2": "production-password-2"}
    )
    monkeypatch.setattr(subscription_service, "SessionLocal", factory)
    monkeypatch.setattr(subscription_service, "_operation_state", lambda *_args: (0, 100))

    assert subscription_service.check_one_pending_charge(settings) is True
    with factory() as db:
        row = db.scalar(select(RecurringSubscription))
        child = db.scalar(select(Payment).where(Payment.external_order_id == "101"))
        assert row is not None and row.status == "active"
        assert row.successful_payments == 2
        assert row.pending_invoice_id is None
        assert row.next_charge_at == row.current_period_end
        assert child is not None and child.payment_status == "paid"
        assert child.raw_payload["reconciled_via"] == "OpStateExt"
    app.dependency_overrides.clear()
