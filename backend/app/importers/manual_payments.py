"""Import private tab-separated manual payment ledgers into CRM.

The input stays outside Git. The command is a dry run unless ``--apply`` is
passed. Rows are idempotent by a hash of their source values.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ImportBatch, MessengerAccount, Payment, Product, User


MOSCOW = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class LedgerPayment:
    row_number: int
    payer_name: str
    paid_at: datetime | None
    amount: Decimal
    payment_method: str
    receipt: str
    comment: str
    row_hash: str


def clean(value: str) -> str:
    return " ".join((value or "").replace("\u00a0", " ").split())


def normalize_identity(value: str) -> str:
    value = clean(value).casefold().replace("ё", "е")
    value = re.sub(r"[^0-9a-zа-я_@]+", " ", value)
    return " ".join(value.split())


def extract_username(value: str) -> str | None:
    match = re.search(r"@([A-Za-z0-9_]{5,})", value or "")
    return match.group(1).casefold() if match else None


def parse_amount(value: str) -> Decimal | None:
    raw = re.sub(r"[^0-9,.-]", "", (value or "").replace("\u00a0", ""))
    if not raw:
        return None
    try:
        amount = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def parse_date(value: str) -> datetime | None:
    raw = clean(value)
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d.%m.%Y").replace(tzinfo=MOSCOW)
    except ValueError:
        return None


def parse_ledger(path: Path) -> list[LedgerPayment]:
    result: list[LedgerPayment] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for row_number, row in enumerate(csv.reader(source, delimiter="\t"), start=1):
            values = list(row) + [""] * max(0, 12 - len(row))
            if clean(values[0]).casefold() == "месяц":
                continue
            if clean(values[6]).casefold() != "true":
                continue
            amount = parse_amount(values[9])
            if amount is None:
                continue
            payer_name = clean(values[1])
            paid_at = parse_date(values[4])
            payment_method = clean(values[8])
            receipt = clean(values[10])
            comment = clean(values[11])
            canonical = "\x1f".join(clean(item) for item in values[:12])
            result.append(
                LedgerPayment(
                    row_number=row_number,
                    payer_name=payer_name,
                    paid_at=paid_at,
                    amount=amount,
                    payment_method=payment_method,
                    receipt=receipt,
                    comment=comment,
                    row_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                )
            )
    return result


def product_for(row: LedgerPayment, products: dict[str, Product]) -> Product | None:
    context = normalize_identity(f"{row.payer_name} {row.comment}")
    if re.search(r"(^| )мк($| )|мастер класс", context):
        return products.get("MASTERCLASS_BASIC")
    return products.get("COACHING")


def import_ledger(
    path: Path,
    *,
    source: str,
    excluded_identities: set[str],
    apply: bool = False,
) -> dict[str, int | bool | str]:
    rows = parse_ledger(path)
    stats: dict[str, int | bool | str] = {
        "source": source,
        "parsed": len(rows),
        "imported": 0,
        "duplicates": 0,
        "matched_by_username": 0,
        "name_candidates": 0,
        "unmatched": 0,
        "excluded_owner": 0,
        "dry_run": not apply,
    }
    excluded = {normalize_identity(item) for item in excluded_identities if clean(item)}
    with SessionLocal() as db:
        batch = ImportBatch(source=source, status="running")
        db.add(batch)
        db.flush()
        products = {item.code: item for item in db.scalars(select(Product))}
        username_rows = db.execute(
            select(MessengerAccount.username, MessengerAccount.user_id).where(
                MessengerAccount.platform == "telegram",
                MessengerAccount.username.is_not(None),
            )
        ).all()
        username_users = {username.casefold(): user_id for username, user_id in username_rows}
        known_names = {
            normalize_identity(name)
            for name in db.scalars(
                select(User.display_name).where(
                    User.display_name.is_not(None), User.merged_into_user_id.is_(None)
                )
            )
        }

        for row in rows:
            identity = normalize_identity(row.payer_name)
            username = extract_username(row.payer_name)
            if identity in excluded or (username and normalize_identity(username) in excluded):
                stats["excluded_owner"] += 1
                continue
            external_id = f"ledger:{row.row_hash}"
            if db.scalar(
                select(Payment.id).where(
                    Payment.source == source,
                    Payment.external_order_id == external_id,
                )
            ):
                stats["duplicates"] += 1
                continue
            user_id = username_users.get(username) if username else None
            if user_id:
                stats["matched_by_username"] += 1
            else:
                if identity and identity in known_names:
                    stats["name_candidates"] += 1
                stats["unmatched"] += 1
            product = product_for(row, products)
            db.add(
                Payment(
                    user_id=user_id,
                    product_id=product.id if product else None,
                    import_batch_id=batch.id,
                    source=source,
                    external_order_id=external_id,
                    product_name_raw=product.name if product else "Ручная историческая оплата",
                    amount=row.amount,
                    amount_is_estimated=False,
                    currency="RUB",
                    payment_status="paid",
                    review_status="pending" if user_id is None or product is None else "not_required",
                    payment_system=row.payment_method or "manual",
                    source_event_at=row.paid_at,
                    paid_at=row.paid_at,
                    paid_at_is_estimated=False,
                    raw_payload={
                        "payer_name": row.payer_name,
                        "receipt": row.receipt,
                        "comment": row.comment,
                        "source_row_number": row.row_number,
                    },
                )
            )
            stats["imported"] += 1
        batch.status = "completed" if apply else "dry_run"
        batch.finished_at = datetime.now(MOSCOW)
        batch.summary = dict(stats)
        if apply:
            db.commit()
        else:
            db.rollback()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a private manual-payment TSV ledger")
    parser.add_argument("tsv", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--apply", action="store_true", help="commit after a reviewed dry run")
    args = parser.parse_args()
    print(
        json.dumps(
            import_ledger(
                args.tsv,
                source=args.source,
                excluded_identities=set(args.exclude),
                apply=args.apply,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
