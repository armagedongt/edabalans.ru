import os
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import Base  # noqa: E402
from app.importers.legacy import import_payload  # noqa: E402
from app.models import (  # noqa: E402
    LegacyImportRecord,
    Payment,
    Resource,
    UserAccess,
    UserEmail,
)


def payload() -> dict:
    product = "Legacy standard product"
    return {
        "standard_calories_cutoff": "2026-08-20 00:00:00",
        "product_aliases": {product: "MASTERCLASS_RECIPES"},
        "clients": [
            [
                "Доступ_МК_Качество",
                "Email",
                "Имя",
                "Username",
                "Telegram ID",
                "Источник:",
                "К_оплате",
                "Тариф_Мастер_класса",
                "Телега_или_Макс",
                "Первая активность",
                "Дата оплаты",
                "",
                "Дата создания",
            ],
            [
                "1",
                "before@example.test",
                "До",
                "before",
                "1001",
                "campaign-a",
                "100",
                "legacy",
                "",
                "10.08.2026",
                "",
                "",
                "10.08.2026",
            ],
        ],
        "payments": [
            [
                "Name",
                "Email",
                "paymentsystem",
                "orderid",
                "paymentid",
                "products",
                "price",
                "Currency",
                "Payment status",
                "referer",
                "formid",
                "Form name",
                "sent",
                "requestid",
                "Валюта",
                "Статус оплаты",
                "Название формы",
                "ma_name",
                "ma_email",
                "ma_phone",
            ],
            [
                "До",
                "before@example.test",
                "test",
                "order-before",
                "payment-before",
                product,
                "100",
                "RUB",
                "Paid",
                "https://example.test/?utm_source=test",
                "form",
                "Cart",
                "2026-08-19 12:00:00",
                "request-before",
            ],
            [
                "После",
                "after@example.test",
                "test",
                "order-after",
                "payment-after",
                product,
                "200",
                "RUB",
                "Paid",
                "https://example.test/",
                "form",
                "Cart",
                "2026-08-20 12:00:00",
                "request-after",
            ],
        ],
    }


def access_codes(db: Session, email: str) -> set[str]:
    return set(
        db.scalars(
            select(Resource.code)
            .join(UserAccess, UserAccess.resource_id == Resource.id)
            .join(UserEmail, UserEmail.user_id == UserAccess.user_id)
            .where(UserEmail.email_normalized == email)
        )
    )


def test_import_is_idempotent_and_applies_historical_calories_rule() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = import_payload(db, payload())
        assert first["payments_imported"] == 2
        assert first["payments_unmapped_product"] == 0
        assert access_codes(db, "before@example.test") == {
            "ACCESS_MASTERCLASS",
            "ACCESS_RECIPES",
            "ACCESS_CALORIES",
        }
        assert access_codes(db, "after@example.test") == {
            "ACCESS_MASTERCLASS",
            "ACCESS_RECIPES",
        }

        second = import_payload(db, payload())
        assert second["payments_imported"] == 0
        assert second["payments_duplicate"] == 2
        assert db.scalar(select(func.count(Payment.id))) == 2


def test_duplicate_unidentified_client_rows_do_not_abort_batch() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    data = payload()
    unidentified = ["177", "", "", "", "", "", "", "", "", "", "", "", ""]
    data["clients"] = [data["clients"][0], unidentified, unidentified.copy()]

    with Session(engine) as db:
        result = import_payload(db, data)
        assert result["clients_needs_review"] == 1
        assert result["clients_duplicate"] == 1
        assert db.scalar(select(func.count(LegacyImportRecord.id))) == 3
