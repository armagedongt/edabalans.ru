from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.app_service import EXTRA_ACCESS_SOURCE, normalize_email
from app.database import SessionLocal
from app.models import Resource, User, UserAccess, UserEmail


RESOURCE_CODES = ("dqs", "strength", "metabolism")


def run(emails: list[str]) -> dict[str, int]:
    normalized_emails = {
        normalize_email(email)
        for email in emails
        if normalize_email(email)
    }
    summary = {
        "requested_emails": len(normalized_emails),
        "matched_users": 0,
        "missing_users": 0,
        "accesses_created": 0,
        "accesses_existing": 0,
    }
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        resources = {
            resource.code: resource
            for resource in db.scalars(
                select(Resource).where(Resource.code.in_(RESOURCE_CODES))
            ).all()
        }
        if set(resources) != set(RESOURCE_CODES):
            raise RuntimeError("Application resources are incomplete")

        users_by_email = {
            email.email_normalized: user
            for email, user in db.execute(
                select(UserEmail, User)
                .join(User, User.id == UserEmail.user_id)
                .where(
                    UserEmail.email_normalized.in_(normalized_emails),
                    User.status == "active",
                    User.merged_into_user_id.is_(None),
                )
            ).all()
        }
        summary["matched_users"] = len(users_by_email)
        summary["missing_users"] = len(normalized_emails - set(users_by_email))

        for user in users_by_email.values():
            for resource in resources.values():
                existing = db.scalar(
                    select(UserAccess)
                    .where(
                        UserAccess.user_id == user.id,
                        UserAccess.resource_id == resource.id,
                        UserAccess.source == EXTRA_ACCESS_SOURCE,
                        UserAccess.revoked_at.is_(None),
                    )
                    .limit(1)
                )
                if existing:
                    summary["accesses_existing"] += 1
                    continue
                db.add(
                    UserAccess(
                        user_id=user.id,
                        resource_id=resource.id,
                        source=EXTRA_ACCESS_SOURCE,
                        granted_at=now,
                    )
                )
                summary["accesses_created"] += 1
        db.commit()
    return summary


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    emails = payload.get("emails", []) if isinstance(payload, dict) else []
    if not isinstance(emails, list):
        raise SystemExit("Expected a JSON object with an emails list")
    print(json.dumps(run([str(email) for email in emails]), ensure_ascii=False))
