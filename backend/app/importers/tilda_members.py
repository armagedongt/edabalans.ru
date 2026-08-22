from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from app.database import SessionLocal
from app.models import (
    ImportBatch,
    LegacyImportRecord,
    Payment,
    Resource,
    User,
    UserAccess,
    UserEmail,
)


MOSCOW = ZoneInfo("Europe/Moscow")
DEFAULT_SOURCE = "tilda_members_20260822T065650"
ACCESS_SOURCE = "tilda_members_legacy"

GROUP_RESOURCES = {
    "Мастер-класс": ("ACCESS_MASTERCLASS",),
    "Мастер-класс (Стандартный)": ("ACCESS_MASTERCLASS",),
    "Мастер-класс (С консультацией)": ("ACCESS_MASTERCLASS",),
    "«Калорийный» курс": ("ACCESS_CALORIES",),
    "Мастер-класс. ОТКРЫТ. Не обновляется.": ("ACCESS_MASTERCLASS_LEGACY",),
    "«Калорийный» курс» ОТКРЫТ. Не обновляется.": ("ACCESS_CALORIES_LEGACY",),
}


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value or value == r"\N":
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=MOSCOW)
    except ValueError:
        return None


def split_groups(value: str) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def usable_display_name(value: str, email: str) -> str | None:
    value = value.strip()
    if not value or value == r"\N" or value.casefold() == email or "@" in value:
        return None
    if re.fullmatch(r"[\d\W_]+", value):
        return None
    return value[:255]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_access(db, user_id, resource: Resource, granted_at: datetime) -> bool:
    existing = db.scalar(
        select(UserAccess.id).where(
            UserAccess.user_id == user_id,
            UserAccess.resource_id == resource.id,
            UserAccess.revoked_at.is_(None),
        )
    )
    if existing is not None:
        return False
    db.add(
        UserAccess(
            user_id=user_id,
            resource_id=resource.id,
            source_payment_id=None,
            source=ACCESS_SOURCE,
            granted_at=granted_at,
        )
    )
    return True


def reconcile_access_queue(db) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    reset = db.execute(
        update(User)
        .where(
            User.access_review_status.in_(("waiting_registration", "pending", "completed")),
            User.access_review_note.is_(None),
            User.access_reviewed_at.is_(None),
        )
        .values(
            access_review_status="not_required",
            access_review_note=None,
            access_reviewed_at=None,
            updated_at=now,
        )
    ).rowcount or 0
    processing_users = select(Payment.user_id).where(
        Payment.payment_status == "processing", Payment.user_id.is_not(None)
    )
    queued = db.execute(
        update(User)
        .where(User.id.in_(processing_users), User.access_review_status != "conflict")
        .values(
            access_review_status="pending",
            access_review_note="Оплата processing — требуется ручная проверка",
            updated_at=now,
        )
    ).rowcount or 0
    return reset, queued


def import_members(path: Path, source: str = DEFAULT_SOURCE, dry_run: bool = False) -> dict[str, int]:
    digest = file_sha256(path)
    counters: defaultdict[str, int] = defaultdict(int)
    seen_emails: set[str] = set()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    with SessionLocal() as db:
        batch = ImportBatch(source=source, status="running")
        db.add(batch)
        db.flush()

        resources = {item.code: item for item in db.scalars(select(Resource))}
        required_codes = {code for codes in GROUP_RESOURCES.values() for code in codes}
        missing = sorted(required_codes - resources.keys())
        if missing:
            raise RuntimeError(f"Missing Tilda access resources: {', '.join(missing)}")

        email_owners = {
            item.email_normalized.casefold(): item
            for item in db.scalars(select(UserEmail))
        }
        existing_hashes = set(
            db.scalars(select(LegacyImportRecord.row_hash).where(LegacyImportRecord.source == source))
        )

        for row_number, row in enumerate(rows, start=1):
            counters["rows"] += 1
            row_hash = hashlib.sha256("\x1f".join(row).encode("utf-8")).hexdigest()
            if row_hash in existing_hashes:
                counters["duplicates"] += 1
                continue

            if len(row) != 7:
                db.add(LegacyImportRecord(
                    import_batch_id=batch.id, source=source, source_row_number=row_number,
                    row_hash=row_hash, status="needs_review", reason=f"Ожидалось 7 колонок, получено {len(row)}",
                    raw_payload={"column_count": len(row), "export_sha256": digest},
                ))
                counters["needs_review"] += 1
                continue

            email = normalize_email(row[0])
            groups = split_groups(row[6])
            created_at = parse_datetime(row[4])
            last_active_at = parse_datetime(row[5])
            if "@" not in email or len(email) > 320 or email in seen_emails:
                db.add(LegacyImportRecord(
                    import_batch_id=batch.id, source=source, source_row_number=row_number,
                    row_hash=row_hash, external_record_id=hashlib.sha256(email.encode()).hexdigest()[:32],
                    status="needs_review", reason="Некорректный или повторяющийся email в выгрузке",
                    raw_payload={"groups": groups, "account_status": row[3], "export_sha256": digest},
                ))
                counters["needs_review"] += 1
                continue
            seen_emails.add(email)

            email_record = email_owners.get(email)
            created_user = email_record is None
            if email_record is None:
                user = User(
                    display_name=usable_display_name(row[1], email),
                    status="active",
                    data_origin="legacy_import",
                    first_seen_at=created_at,
                )
                db.add(user)
                db.flush()
                email_record = UserEmail(
                    user_id=user.id,
                    email_original=row[0].strip(),
                    email_normalized=email,
                    is_primary=True,
                    verification_status="tilda_registered",
                    source=ACCESS_SOURCE,
                    first_seen_at=created_at,
                )
                db.add(email_record)
                email_owners[email] = email_record
                counters["users_created"] += 1
            else:
                user = db.get(User, email_record.user_id)
                email_record.verification_status = "tilda_registered"
                counters["users_matched"] += 1

            if user is None or user.merged_into_user_id is not None:
                db.add(LegacyImportRecord(
                    import_batch_id=batch.id, source=source, source_row_number=row_number,
                    row_hash=row_hash, external_record_id=hashlib.sha256(email.encode()).hexdigest()[:32],
                    status="needs_review", reason="Email связан с объединённой или отсутствующей записью",
                    raw_payload={"groups": groups, "account_status": row[3], "export_sha256": digest},
                ))
                counters["needs_review"] += 1
                continue

            granted_at = created_at or datetime.now(timezone.utc)
            resource_codes = {
                code for group in groups for code in GROUP_RESOURCES.get(group, ())
            }
            for code in resource_codes:
                if ensure_access(db, user.id, resources[code], granted_at):
                    counters["accesses_granted"] += 1
            counters["current_masterclass"] += int("ACCESS_MASTERCLASS" in resource_codes)
            counters["current_calories"] += int("ACCESS_CALORIES" in resource_codes)
            counters["legacy_masterclass"] += int("ACCESS_MASTERCLASS_LEGACY" in resource_codes)
            counters["legacy_calories"] += int("ACCESS_CALORIES_LEGACY" in resource_codes)
            counters["without_core_access"] += int(not resource_codes)

            user.tilda_access_status = "granted" if groups else "not_required"
            if user.access_review_status != "conflict":
                user.access_review_status = "not_required"
                user.access_review_note = None
                user.access_reviewed_at = None

            db.add(LegacyImportRecord(
                import_batch_id=batch.id,
                source=source,
                source_row_number=row_number,
                row_hash=row_hash,
                external_record_id=hashlib.sha256(email.encode()).hexdigest()[:32],
                status="imported",
                user_id=user.id,
                reason="created_new" if created_user else "matched_existing",
                raw_payload={
                    "groups": groups,
                    "account_status": row[3],
                    "member_created_at": created_at.isoformat() if created_at else None,
                    "last_active_at": last_active_at.isoformat() if last_active_at else None,
                    "resource_codes": sorted(resource_codes),
                    "export_sha256": digest,
                },
            ))
            counters["imported"] += 1

        reset, queued = reconcile_access_queue(db)
        counters["review_queue_reset"] = reset
        counters["review_queue_processing"] = queued
        batch.status = "dry_run" if dry_run else "completed"
        batch.finished_at = datetime.now(timezone.utc)
        batch.summary = dict(counters)
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return dict(counters)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import canonical Tilda Members Area CSV")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(import_members(args.csv, source=args.source, dry_run=args.dry_run), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
