import csv
import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.database import Base  # noqa: E402
from app.importers import tilda_members  # noqa: E402
from app.models import Payment, Resource, User, UserAccess, UserEmail  # noqa: E402


RESOURCE_NAMES = {
    "ACCESS_MASTERCLASS": "Мастер-класс",
    "ACCESS_CALORIES": "Курс о калориях",
    "ACCESS_MASTERCLASS_LEGACY": "Мастер-класс — старая необновляемая версия",
    "ACCESS_CALORIES_LEGACY": "Курс о калориях — старая необновляемая версия",
}


def prepare(tmp_path, monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(tilda_members, "SessionLocal", factory)
    with factory() as db:
        db.add_all(Resource(code=code, name=name) for code, name in RESOURCE_NAMES.items())
        db.commit()
    path = tmp_path / "members.csv"
    return factory, path


def write_rows(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(rows)


def access_codes(db: Session, email: str) -> set[str]:
    return set(db.scalars(
        select(Resource.code)
        .join(UserAccess, UserAccess.resource_id == Resource.id)
        .join(UserEmail, UserEmail.user_id == UserAccess.user_id)
        .where(UserEmail.email_normalized == email, UserAccess.revoked_at.is_(None))
    ))


def test_tilda_groups_map_to_current_and_non_updating_access(tmp_path, monkeypatch) -> None:
    factory, path = prepare(tmp_path, monkeypatch)
    write_rows(path, [
        ["current@example.test", "Ирина", r"\N", "Active", "2026-01-01 10:00:00", "2026-08-21 12:00:00",
         "Мастер-класс (Стандартный),«Калорийный» курс,Книга рецептов"],
        ["legacy@example.test", "", r"\N", "Active", "2025-01-01 10:00:00", "2026-08-20 12:00:00",
         "Мастер-класс. ОТКРЫТ. Не обновляется.,«Калорийный» курс» ОТКРЫТ. Не обновляется."],
    ])

    first = tilda_members.import_members(path, source="tilda_members_test")
    assert first["imported"] == 2
    assert first["accesses_granted"] == 4
    with factory() as db:
        assert access_codes(db, "current@example.test") == {
            "ACCESS_MASTERCLASS", "ACCESS_CALORIES"
        }
        assert access_codes(db, "legacy@example.test") == {
            "ACCESS_MASTERCLASS_LEGACY", "ACCESS_CALORIES_LEGACY"
        }
        assert set(db.scalars(select(User.tilda_access_status))) == {"granted"}
        assert set(db.scalars(select(UserEmail.verification_status))) == {"tilda_registered"}

    second = tilda_members.import_members(path, source="tilda_members_test")
    assert second["duplicates"] == 2
    with factory() as db:
        assert db.scalar(select(func.count(User.id))) == 2
        assert db.scalar(select(func.count(UserAccess.id))) == 4


def test_import_preserves_historical_review_queue_and_adds_processing(tmp_path, monkeypatch) -> None:
    factory, path = prepare(tmp_path, monkeypatch)
    write_rows(path, [[
        "member@example.test", "", r"\N", "Active", "2026-01-01 10:00:00",
        "2026-08-21 12:00:00", "Мастер-класс"
    ]])
    with factory() as db:
        old = User(status="active", data_origin="legacy_import", access_review_status="waiting_registration")
        processing = User(status="active", data_origin="legacy_import", access_review_status="pending")
        db.add_all([old, processing])
        db.flush()
        old_id = old.id
        processing_id = processing.id
        db.add(Payment(
            user_id=processing_id, source="test", external_order_id="processing-1",
            product_name_raw="Мастер-класс", amount=1000, currency="RUB",
            payment_status="processing", source_event_at=datetime.now(timezone.utc),
        ))
        db.commit()

    tilda_members.import_members(path, source="tilda_members_queue_test")
    with factory() as db:
        statuses = {str(user.id): (user.access_review_status, user.access_review_note)
                    for user in db.scalars(select(User))}
        assert statuses[str(old_id)] == ("waiting_registration", None)
        assert statuses[str(processing_id)][0] == "pending"
        assert "processing" in statuses[str(processing_id)][1]


def test_welcome_only_requires_review_but_welcome_plus_product_is_processed(tmp_path, monkeypatch) -> None:
    factory, path = prepare(tmp_path, monkeypatch)
    write_rows(path, [
        ["welcome@example.test", "", r"\N", "Active", "2026-01-01 10:00:00", "2026-08-21 12:00:00", "Добро пожаловать"],
        ["processed@example.test", "", r"\N", "Active", "2026-01-01 10:00:00", "2026-08-21 12:00:00", "Добро пожаловать,Мастер-класс"],
    ])
    tilda_members.import_members(path, source="tilda_members_welcome_test")
    with factory() as db:
        rows = {
            email.email_normalized: db.get(User, email.user_id)
            for email in db.scalars(select(UserEmail))
        }
        assert rows["welcome@example.test"].access_review_status == "pending"
        assert "решения Сергея" in rows["welcome@example.test"].access_review_note
        assert rows["processed@example.test"].access_review_status == "not_required"
        assert access_codes(db, "processed@example.test") == {"ACCESS_MASTERCLASS"}
