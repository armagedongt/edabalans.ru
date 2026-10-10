"""Prepare Tilda accounts and a private mailing manifest, without queueing mail."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.access_service import EMAIL_RE, complete_review
from app.config import get_settings
from app.crm_service import _issue_account_password
from app.database import SessionLocal
from app.importers.tilda_members import GROUP_RESOURCES, normalize_email, usable_display_name
from app.models import (AccountCredential, AdminAppEdit, LegacyImportRecord,
                        Resource, User, UserAccess, UserCoursePolicy, UserEmail)
from app.course_access_service import active_resource_codes
from app.tilda_service import OFFER_RESOURCE_COMPANIONS

SOURCE = "tilda_account_transfer"
EXCLUDED_EMAILS = {"armagedongt@gmail.com"}
EXTRA_GROUPS = {"Книга рецептов": ("ACCESS_RECIPES",)}
COURSES = {"ACCESS_MASTERCLASS", "ACCESS_MASTERCLASS_LEGACY", "ACCESS_CALORIES",
           "ACCESS_CALORIES_LEGACY", "ACCESS_RECIPES"}


def parse_members(path: Path) -> list[dict]:
    members, seen = [], set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) != 7:
                raise ValueError("Expected seven Tilda export columns")
            email = normalize_email(row[0])
            if not EMAIL_RE.match(email) or email in seen:
                raise ValueError("Invalid or repeated Tilda email")
            seen.add(email)
            if email in EXCLUDED_EMAILS:
                continue
            groups = [g.strip() for g in row[6].split(",") if g.strip()]
            codes = sorted({code for g in groups for code in
                            GROUP_RESOURCES.get(g, EXTRA_GROUPS.get(g, ()))})
            members.append({"email": email, "name": usable_display_name(row[1], email),
                            "groups": groups, "codes": codes})
    return members


def ensure_right(db, user, resource, skipped):
    rows = list(db.scalars(select(UserAccess).where(
        UserAccess.user_id == user.id, UserAccess.resource_id == resource.id)))
    now = datetime.now(timezone.utc)
    if any(r.revoked_at is None and r.paused_at is None and
           (r.expires_at is None or (r.expires_at.replace(tzinfo=timezone.utc)
                                    if r.expires_at.tzinfo is None else r.expires_at) > now)
           for r in rows):
        return
    # Explicit prior exclusions must survive migration from a historical snapshot.
    if rows:
        skipped.append(resource.code)
        return
    db.add(UserAccess(user_id=user.id, resource_id=resource.id, source=SOURCE,
                      granted_at=now))
    db.flush()


def prepare(db, members: list[dict], settings, batch: str, source_sha256: str) -> dict:
    resources = {r.code: r for r in db.scalars(select(Resource).where(Resource.status == "active"))}
    needed = {c for m in members for c in m["codes"]}
    needed.update(c for r in needed.copy() for c in OFFER_RESOURCE_COMPANIONS.get(r, ()))
    if "ACCESS_CALORIES_LEGACY" in needed:
        needed.add("metabolism")
    if needed - resources.keys():
        raise ValueError("Missing resources: " + ", ".join(sorted(needed - resources.keys())))
    report = {"batch": batch, "source_sha256": source_sha256, "recipients": [],
              "excluded_emails": sorted(EXCLUDED_EMAILS), "passwords_created": 0,
              "accounts_created": 0, "messages_queued": 0}
    for member in members:
        email_row = db.scalar(select(UserEmail).where(UserEmail.email_normalized == member["email"]))
        user = db.scalar(select(User).where(User.id == email_row.user_id).with_for_update()) if email_row else None
        if email_row and (user is None or user.merged_into_user_id or user.status != "active"):
            raise ValueError("Tilda email points to an inactive or merged account")
        if user is None:
            user = User(display_name=member["name"], status="active", data_origin="legacy_import",
                        access_review_status="pending", tilda_access_status="pending")
            db.add(user)
            db.flush()
            db.add(UserEmail(user_id=user.id, email_original=member["email"],
                             email_normalized=member["email"], is_primary=True,
                             verification_status="tilda_registered", source=SOURCE))
            report["accounts_created"] += 1
        credential = db.get(AccountCredential, user.id)
        account_existing = credential is not None
        if credential is None:
            _, credential = _issue_account_password(db, user, settings, SOURCE)
            report["passwords_created"] += 1
        skipped = []
        for code in member["codes"]:
            ensure_right(db, user, resources[code], skipped)
        owned = active_resource_codes(db, user.id)
        for code in sorted(owned & COURSES & set(member["codes"])):
            policy = db.scalar(select(UserCoursePolicy).where(
                UserCoursePolicy.user_id == user.id, UserCoursePolicy.resource_id == resources[code].id))
            if policy is None:
                db.add(UserCoursePolicy(user_id=user.id, resource_id=resources[code].id,
                                        start_mode="open", unlock_mode="fully_unlocked" if code == "ACCESS_RECIPES" else "paced",
                                        course_policy_version=2 if code == "ACCESS_MASTERCLASS" else 1,
                                        source=SOURCE))
            elif policy.source != "manual_admin" and policy.start_mode == "auto":
                policy.start_mode = "open"
            companions = OFFER_RESOURCE_COMPANIONS.get(code, ())
            if code == "ACCESS_CALORIES_LEGACY":
                companions = ("metabolism",)
            for companion in companions:
                ensure_right(db, user, resources[companion], skipped)
        if member["codes"] and user.access_review_status != "conflict":
            complete_review(user, "Перенос Tilda: " + batch)
        email_hash = hashlib.sha256(member["email"].encode()).hexdigest()[:32]
        for orphan in db.scalars(select(LegacyImportRecord).where(
                LegacyImportRecord.source.like("tilda_members_%"),
                LegacyImportRecord.external_record_id == email_hash,
                LegacyImportRecord.user_id.is_(None))):
            orphan.user_id = user.id
        db.flush()
        final_owned = active_resource_codes(db, user.id)
        recipient = {**member, "user_id": str(user.id), "account_existing": account_existing,
                     "password_version": credential.password_version,
                     "rights": sorted(final_owned), "skipped_rights": skipped,
                     "review_status": user.access_review_status}
        report["recipients"].append(recipient)
        db.add(AdminAppEdit(admin_username=SOURCE, target_user_id=user.id, app_code="crm",
                            action="prepare_tilda_account",
                            details={"batch": batch, "source_sha256": source_sha256,
                                     "groups": member["groups"], "rights": sorted(final_owned),
                                     "password_version": credential.password_version,
                                     "skipped_rights": skipped}))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError("Personal mailing manifests must stay outside the repository")
    members = parse_members(args.csv)
    sha = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    with SessionLocal() as db:
        report = prepare(db, members, get_settings(), args.batch, sha)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        args.output.chmod(0o600)
        db.commit() if args.apply else db.rollback()
    print(json.dumps({"recipients": len(report["recipients"]),
                      "passwords_created": report["passwords_created"],
                      "accounts_created": report["accounts_created"],
                      "messages_queued": 0, "applied": args.apply}))


if __name__ == "__main__":
    main()
