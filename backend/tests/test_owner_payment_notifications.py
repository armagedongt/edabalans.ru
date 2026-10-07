import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import Settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import MessengerAccount, OfferCheckout, OwnerPaymentNotification, Payment, Product, User, UserEmail  # noqa: E402
import app.owner_payment_notification_service as notification_service  # noqa: E402


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _paid_payment(*, raw_payload: dict | None = None) -> Payment:
    return Payment(
        source="robokassa",
        external_order_id="812345",
        email_at_purchase="buyer@example.test",
        product_name_raw="Сопровождение",
        amount=Decimal("9900.00"),
        currency="RUB",
        payment_status="paid",
        paid_at=datetime.now(timezone.utc),
        raw_payload=raw_payload or {},
    )


def test_paid_owner_alert_is_durable_idempotent_and_delivered(monkeypatch) -> None:
    factory = _factory()
    with factory() as db:
        payment = _paid_payment()
        db.add(payment)
        db.flush()
        db.add(
            OfferCheckout(
                checkout_kind="manual_service",
                offer_code="manual.payment",
                title="Сопровождение",
                items=[],
                amount=Decimal("9900.00"),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                payment_id=payment.id,
            )
        )
        payment.raw_payload = {"payer_name": "Покупатель", "comment": "Консультация"}
        first = notification_service.enqueue_paid_payment_notification(db, payment)
        second = notification_service.enqueue_paid_payment_notification(db, payment)
        db.commit()
        assert first is second

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_auth_secret="owner-alert-tests",
        payment_owner_alerts_enabled=True,
        payment_owner_alerts_endpoint="http://telegram-bot:8001/internal/owner-payment-alert",
    )
    delivered = []
    monkeypatch.setattr(notification_service, "SessionLocal", factory)
    monkeypatch.setattr(
        notification_service,
        "_deliver",
        lambda _settings, row: delivered.append(row.message_text) or "telegram-42",
    )

    assert notification_service.send_one_owner_payment_notification(settings) is True
    assert delivered[0].startswith("<b>$ Индив. оплата · 9 900 ₽</b>\n\n")
    assert "Сопровождение" in delivered[0]
    with factory() as db:
        rows = db.scalars(select(OwnerPaymentNotification)).all()
        assert len(rows) == 1
        assert rows[0].status == "sent"
        assert rows[0].delivery_message_id == "telegram-42"


def test_test_and_live_probe_payments_do_not_enqueue_owner_alerts() -> None:
    factory = _factory()
    with factory() as db:
        test_payment = _paid_payment(raw_payload={"integration": {"test_mode": True}})
        probe_payment = _paid_payment(raw_payload={"integration": {"live_probe": True}})
        probe_payment.external_order_id = "812346"
        db.add_all((test_payment, probe_payment))
        db.flush()
        assert notification_service.enqueue_paid_payment_notification(db, test_payment) is None
        assert notification_service.enqueue_paid_payment_notification(db, probe_payment) is None
        db.commit()
        assert db.scalars(select(OwnerPaymentNotification)).all() == []


def test_failed_owner_alert_starts_with_payment_error() -> None:
    factory = _factory()
    with factory() as db:
        payment = _paid_payment()
        payment.payment_status = "failed"
        db.add(payment)
        db.flush()

        notification = notification_service.enqueue_failed_payment_notification(
            db, payment, "Недостаточно средств"
        )

        assert notification is not None
        assert notification.message_text.startswith("<b>❌ Ошибка оплаты · 9 900 ₽</b>\n\n")
        assert "Статус Robokassa: Недостаточно средств" in notification.message_text


def test_delivery_failure_stays_in_durable_retry_queue(monkeypatch) -> None:
    factory = _factory()
    with factory() as db:
        payment = _paid_payment()
        db.add(payment)
        db.flush()
        notification_service.enqueue_paid_payment_notification(db, payment)
        db.commit()

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_auth_secret="owner-alert-tests",
        payment_owner_alerts_enabled=True,
    )
    monkeypatch.setattr(notification_service, "SessionLocal", factory)
    monkeypatch.setattr(
        notification_service,
        "_deliver",
        lambda *_args: (_ for _ in ()).throw(OSError("relay down")),
    )

    assert notification_service.send_one_owner_payment_notification(settings) is True
    with factory() as db:
        row = db.scalar(select(OwnerPaymentNotification))
        assert row is not None and row.status == "retry"
        assert row.attempt_count == 1
        assert row.next_attempt_at is not None
        assert row.last_error == "relay down"


@pytest.mark.parametrize("kind,metadata,heading,place", [
    ("public_site_robokassa", {"account_purchase": False, "purchase_place": "homepage"}, "Новая покупка", "Главная страница"),
    ("public_site_robokassa", {"account_purchase": False}, "Новая покупка", "Публичный сайт (страница не сохранена)"),
    ("public_site_robokassa", {"account_purchase": True, "purchase_place": "account"}, "Доп. продажа", "Личный кабинет"),
    ("member_offer", {"account_purchase": True, "purchase_place": "course"}, "Доп. продажа", "Материалы Мастер-класса"),
    ("personal_access_paid", {"personal_access_link_id": "offer"}, "Перс. предложение", "Персональная ссылка"),
    ("recurring_subscription", {"recurring_role": "child"}, "Продление подписки", "Автоматическое списание"),
    ("recurring_subscription", {"recurring_role": "parent"}, "Оплата подписки", "Страница подписки"),
])
def test_purchase_route_survives_post_paid_account_attachment(kind, metadata, heading, place):
    factory = _factory()
    with factory() as db:
        user = User()
        db.add(user)
        db.flush()
        payment = _paid_payment(raw_payload=metadata)
        payment.user_id = user.id
        db.add(payment)
        db.flush()
        db.add(OfferCheckout(user_id=user.id, checkout_kind=kind, offer_code="offer", title="Offer", items=[],
                             amount=payment.amount, expires_at=datetime.now(timezone.utc), payment_id=payment.id))
        db.flush()
        row = notification_service.enqueue_paid_payment_notification(db, payment)
        assert f"$ {heading} · 9 900 ₽" in row.message_text
        assert f"Место покупки: {place}" in row.message_text


def test_tariff_is_in_product_line_and_customer_html_is_escaped():
    factory = _factory()
    with factory() as db:
        user = User()
        product = Product(code="MASTERCLASS_RECIPES", name="Tariff")
        db.add_all([user, product])
        db.flush()
        payment = _paid_payment(raw_payload={"account_purchase": False})
        payment.user_id, payment.product_id = user.id, product.id
        payment.product_name_raw = "Стандартный"
        db.add(payment)
        db.add(MessengerAccount(user_id=user.id, platform="telegram", platform_user_id="123",
                                first_name='<b>A&B</b>', source="account", linked_at=datetime.now(timezone.utc)))
        db.flush()
        row = notification_service.enqueue_paid_payment_notification(db, payment)
        assert "Продукт: Мастер-класс + Система рецептов — Стандартный" in row.message_text
        assert "Тариф:" not in row.message_text
        assert 'href="tg://user?id=123"' in row.message_text
        assert "&lt;b&gt;A&amp;B&lt;/b&gt;" in row.message_text
        assert f"crm?user={user.id}" in row.message_text


def test_linking_messenger_refreshes_existing_notification_without_another_purchase(monkeypatch):
    factory = _factory()
    delivered = []
    monkeypatch.setattr(notification_service, "SessionLocal", factory)
    monkeypatch.setattr(notification_service, "_deliver", lambda _settings, row: delivered.append((row.id, row.message_text)) or "42")
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    with factory() as db:
        user = User()
        db.add(user)
        db.flush()
        payment = _paid_payment()
        payment.user_id = user.id
        db.add_all([payment, UserEmail(user_id=user.id, email_original=payment.email_at_purchase,
                                     email_normalized=payment.email_at_purchase, source="robokassa")])
        db.flush()
        notification_service.enqueue_paid_payment_notification(db, payment)
        db.commit()
        uid = user.id
    assert notification_service.send_one_owner_payment_notification(settings)
    with factory() as db:
        row = db.scalar(select(OwnerPaymentNotification))
        db.add(MessengerAccount(user_id=uid, platform="telegram", platform_user_id="123", username="buyer",
                                source="account", linked_at=row.sent_at + timedelta(seconds=1)))
        db.commit()
    assert notification_service.send_one_owner_payment_notification(settings)
    assert len(delivered) == 2 and delivered[0][0] == delivered[1][0]
    assert "не привязан" in delivered[0][1]
    assert 'href="https://t.me/buyer"' in delivered[1][1]
    assert not notification_service.send_one_owner_payment_notification(settings)
