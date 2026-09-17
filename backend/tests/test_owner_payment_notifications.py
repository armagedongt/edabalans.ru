import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import Settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import OfferCheckout, OwnerPaymentNotification, Payment  # noqa: E402
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
    assert "Оплата прошла" in delivered[0]
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
