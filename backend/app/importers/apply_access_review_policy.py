from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.database import SessionLocal
from app.importers.tilda_members import REVIEW_NOTE, WELCOME_GROUP
from app.models import LegacyImportRecord, Payment, User


CONFIRMED = {"paid", "confirmed"}


def classify(db) -> tuple[dict, Counter]:
    latest: dict = {}
    rows = db.scalars(
        select(LegacyImportRecord)
        .where(
            LegacyImportRecord.source.like("tilda_members_%"),
            LegacyImportRecord.user_id.is_not(None),
        )
        .order_by(LegacyImportRecord.created_at.asc())
    )
    for row in rows:
        latest[row.user_id] = row

    buyers = set(
        db.scalars(
            select(Payment.user_id).where(
                Payment.user_id.is_not(None),
                Payment.payment_status.in_(CONFIRMED),
            )
        )
    )
    desired: dict = {}
    counts: Counter = Counter()
    for user_id in buyers | set(latest):
        record = latest.get(user_id)
        groups = list((record.raw_payload or {}).get("groups") or []) if record else []
        product_groups = [group for group in groups if group != WELCOME_GROUP]
        if record and product_groups:
            desired[user_id] = ("not_required", "granted", None)
            counts["tilda_processed"] += 1
        elif record:
            desired[user_id] = ("pending", "pending", REVIEW_NOTE)
            counts["tilda_welcome_only"] += 1
        elif user_id in buyers:
            desired[user_id] = ("waiting_registration", "not_checked", REVIEW_NOTE)
            counts["buyer_without_tilda"] += 1
    return desired, counts


def run(*, apply: bool = False, backup_confirmed: bool = False) -> dict[str, int]:
    if apply and not backup_confirmed:
        raise RuntimeError("--apply requires --backup-confirmed")
    with SessionLocal() as db:
        desired, counts = classify(db)
        changed = 0
        preserved_conflicts = 0
        for user_id, (status, tilda_status, note) in desired.items():
            user = db.get(User, user_id)
            if user is None or user.merged_into_user_id is not None:
                continue
            if user.access_review_status == "conflict":
                preserved_conflicts += 1
                continue
            before = (user.access_review_status, user.tilda_access_status, user.access_review_note)
            after = (status, tilda_status, note)
            if before != after:
                changed += 1
                if apply:
                    user.access_review_status = status
                    user.tilda_access_status = tilda_status
                    user.access_review_note = note
                    user.access_reviewed_at = None
        if apply:
            db.commit()
        else:
            db.rollback()
        return {
            **counts,
            "changed": changed,
            "preserved_conflicts": preserved_conflicts,
            "applied": int(apply),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify access review from canonical Tilda snapshot")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    args = parser.parse_args()
    print(run(apply=args.apply, backup_confirmed=args.backup_confirmed))


if __name__ == "__main__":
    main()
