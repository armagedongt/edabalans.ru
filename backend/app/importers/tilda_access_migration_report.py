from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AccountCredential,
    LegacyImportRecord,
    MasterclassDayProgress,
    MessengerAccount,
    Resource,
    User,
    UserAccess,
    UserEmail,
)


HEADERS = (
    "Email",
    "Имя",
    "Дата регистрации в Tilda",
    "Группы Tilda",
    "Доступы в новой базе",
    "Версия Мастер-класса",
    "Пароль",
    "Telegram ID",
    "MAX ID",
    "Последний открытый день",
    "Пройденные дни",
    "Открыть дней вручную",
    "Решение по миграции",
    "Комментарий",
)


def spreadsheet_safe(value: object) -> str:
    text_value = "" if value is None else str(value)
    if text_value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text_value
    return text_value


def migration_rows(db: Session) -> list[dict[str, str]]:
    snapshots: dict[str, LegacyImportRecord] = {}
    for item in db.scalars(
        select(LegacyImportRecord)
        .where(
            LegacyImportRecord.source.like("tilda_members_%"),
            LegacyImportRecord.status == "imported",
            LegacyImportRecord.user_id.is_not(None),
        )
        .order_by(LegacyImportRecord.created_at.desc())
    ):
        snapshots.setdefault(str(item.user_id), item)

    user_ids = [item.user_id for item in snapshots.values()]
    if not user_ids:
        return []

    users = {
        str(item.id): item
        for item in db.scalars(select(User).where(User.id.in_(user_ids)))
    }
    emails: dict[str, str] = {}
    for item in db.scalars(
        select(UserEmail)
        .where(UserEmail.user_id.in_(user_ids))
        .order_by(UserEmail.is_primary.desc(), UserEmail.created_at)
    ):
        emails.setdefault(str(item.user_id), item.email_normalized)

    now = datetime.now(UTC)
    access_codes: defaultdict[str, list[str]] = defaultdict(list)
    for user_id, code in db.execute(
        select(UserAccess.user_id, Resource.code)
        .join(Resource, Resource.id == UserAccess.resource_id)
        .where(
            UserAccess.user_id.in_(user_ids),
            Resource.status == "active",
            UserAccess.revoked_at.is_(None),
            (UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now)),
        )
        .order_by(Resource.code)
    ):
        access_codes[str(user_id)].append(code)

    credentials = {
        str(user_id)
        for user_id in db.scalars(
            select(AccountCredential.user_id).where(AccountCredential.user_id.in_(user_ids))
        )
    }
    messengers: dict[tuple[str, str], str] = {}
    for item in db.scalars(
        select(MessengerAccount)
        .where(
            MessengerAccount.user_id.in_(user_ids),
            MessengerAccount.platform.in_(("telegram", "max")),
            MessengerAccount.linked_at.is_not(None),
        )
        .order_by(MessengerAccount.linked_at.desc())
    ):
        messengers.setdefault(
            (str(item.user_id), item.platform),
            item.platform_user_id,
        )

    opened_through: defaultdict[str, int] = defaultdict(int)
    completed_days: defaultdict[str, list[str]] = defaultdict(list)
    for progress in db.scalars(
        select(MasterclassDayProgress)
        .where(MasterclassDayProgress.user_id.in_(user_ids))
        .order_by(MasterclassDayProgress.day_number)
    ):
        key = str(progress.user_id)
        opened_through[key] = max(opened_through[key], progress.day_number)
        if progress.completed_at is not None:
            completed_days[key].append(str(progress.day_number))

    rows: list[dict[str, str]] = []
    for user_id, snapshot in snapshots.items():
        user = users.get(user_id)
        raw = dict(snapshot.raw_payload or {})
        codes = access_codes[user_id]
        if "ACCESS_MASTERCLASS" in codes:
            masterclass_version = "текущий"
        elif "ACCESS_MASTERCLASS_LEGACY" in codes:
            masterclass_version = "старый"
        else:
            masterclass_version = "нет"
        if user_id in credentials:
            password_status = "уже выдан; повторно не показывается"
        else:
            password_status = "создать при согласованной рассылке"
        rows.append(
            {
                "Email": emails.get(user_id, ""),
                "Имя": user.display_name or "" if user else "",
                "Дата регистрации в Tilda": str(raw.get("member_created_at") or ""),
                "Группы Tilda": " | ".join(raw.get("groups") or []),
                "Доступы в новой базе": " | ".join(codes),
                "Версия Мастер-класса": masterclass_version,
                "Пароль": password_status,
                "Telegram ID": messengers.get((user_id, "telegram"), ""),
                "MAX ID": messengers.get((user_id, "max"), ""),
                "Последний открытый день": str(opened_through[user_id] or ""),
                "Пройденные дни": ", ".join(completed_days[user_id]),
                "Открыть дней вручную": "",
                "Решение по миграции": "",
                "Комментарий": (
                    f"{user.access_review_status}: {user.access_review_note or ''}".strip(": ")
                    if user and user.access_review_status not in {"not_required", None}
                    else ""
                ),
            }
        )
    return sorted(rows, key=lambda item: item["Email"].casefold())


def write_report(output: Path) -> dict[str, int | str]:
    with SessionLocal() as db:
        rows = migration_rows(db)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, delimiter=";")
        writer.writeheader()
        writer.writerows(
            {key: spreadsheet_safe(value) for key, value in row.items()}
            for row in rows
        )
    return {"rows": len(rows), "output": str(output.resolve())}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the read-only Tilda-to-native account migration review table"
    )
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(write_report(args.output), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
