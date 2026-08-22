"""Apply the owner-approved, reversible CRM cleanup after migration 0007.

The operation is idempotent. It never grants product access and never deletes legacy rows.
"""

from __future__ import annotations

import json
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import AttributionEvent, Payment, Tag, User, UserEmail

PLAN = Path(__file__).resolve().parents[1] / "static" / "leadteh_tag_plan.json"
CONFIRMED = ("paid", "confirmed")


def code_for(name: str) -> str:
    value = re.sub(r"[^a-z0-9а-яё]+", "_", name.lower(), flags=re.I).strip("_")[:58]
    suffix = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"clean_{value}_{suffix}"


def apply() -> dict[str, int]:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    stats = {"tags_archived": 0, "tags_merged": 0, "sources_created": 0,
             "historical_payments": 0, "first_visits": 0, "reviews_queued": 0}
    with SessionLocal() as db:
        tags = {str(tag.id): tag for tag in db.scalars(select(Tag))}
        for item in plan:
            tag = tags.get(item["id"])
            if tag is None:
                continue
            tag.category = item["group"]
            tag.audit_action = item["action"]
            tag.audit_reason = item["reason"]
            tag.updated_at = datetime.now(timezone.utc)
            action = item["action"]
            if action == "rename":
                target_name = item["proposed_name"]
                target = db.scalar(select(Tag).where(Tag.name == target_name, Tag.id != tag.id))
                if target is None:
                    target = Tag(code=code_for(target_name), name=target_name, category="content",
                                 status="active", audit_action="keep",
                                 audit_reason="Каноническое название материала")
                    db.add(target)
                    db.flush()
                tag.status = "merged"
                tag.merged_into_tag_id = target.id
                stats["tags_merged"] += 1
            elif action == "convert_source":
                rows = db.execute(text("SELECT user_id, min(created_at) occurred_at FROM user_tags WHERE tag_id=:id GROUP BY user_id"), {"id": tag.id}).all()
                for user_id, occurred_at in rows:
                    exists = db.scalar(select(AttributionEvent.id).where(
                        AttributionEvent.user_id == user_id,
                        AttributionEvent.event_type == "legacy_tag_source",
                        AttributionEvent.source_raw == item["proposed_name"],
                    ))
                    if not exists:
                        db.add(AttributionEvent(user_id=user_id, event_type="legacy_tag_source",
                                                source_raw=item["proposed_name"], occurred_at=occurred_at))
                        stats["sources_created"] += 1
                tag.status = "archived"
                tag.archived_at = datetime.now(timezone.utc)
                stats["tags_archived"] += 1
            elif action == "convert_state":
                tag.status = "archived"
                tag.archived_at = datetime.now(timezone.utc)
                stats["tags_archived"] += 1
            elif action in {"archive", "use_for_review", "convert_payment"}:
                tag.status = "archived"
                tag.archived_at = datetime.now(timezone.utc)
                stats["tags_archived"] += 1
            elif action == "review":
                tag.status = "review"
            else:
                tag.status = "active"

            if item["current_name"] == "Первое посещение":
                result = db.execute(text("""
                    UPDATE messenger_accounts m SET main_scenario_seen_at=COALESCE(m.main_scenario_seen_at,u.created_at)
                    FROM user_tags u WHERE u.tag_id=:tag_id AND u.user_id=m.user_id AND m.platform='telegram'
                """), {"tag_id": tag.id})
                stats["first_visits"] += result.rowcount or 0

        # Every imported Google client is a confirmed historical buyer. Existing paid/confirmed
        # facts win; processing records remain untouched for manual review.
        google_users = db.execute(text("""
            SELECT DISTINCT user_id FROM legacy_import_records
            WHERE source='google_clients_legacy' AND user_id IS NOT NULL AND status='imported'
        """)).scalars().all()
        for user_id in google_users:
            confirmed = db.scalar(select(Payment.id).where(Payment.user_id == user_id,
                                                           Payment.payment_status.in_(CONFIRMED)))
            if not confirmed:
                db.add(Payment(user_id=user_id, source="google_clients_legacy",
                    external_order_id=f"historical-client-{user_id}", product_name_raw="Историческая покупка",
                    amount=None, currency="RUB", payment_status="confirmed", review_status="pending"))
                stats["historical_payments"] += 1

        # Two owner-confirmed LeadTeh signals can establish a historical purchase fact.
        for item in plan:
            if item["action"] != "convert_payment":
                continue
            product_raw = "Мастер-класс" if item["current_name"] == "МК Оплатил" else "Курс о калориях"
            for user_id in db.execute(text("SELECT user_id FROM user_tags WHERE tag_id=:id"), {"id": item["id"]}).scalars():
                exists = db.scalar(select(Payment.id).where(Payment.user_id == user_id,
                    Payment.source == "leadteh_legacy", Payment.external_order_id == f"tag-{item['id']}-{user_id}"))
                confirmed = db.scalar(select(Payment.id).where(Payment.user_id == user_id,
                    Payment.payment_status.in_(CONFIRMED), Payment.product_name_raw == product_raw))
                if not exists and not confirmed:
                    db.add(Payment(user_id=user_id, source="leadteh_legacy",
                        external_order_id=f"tag-{item['id']}-{user_id}", product_name_raw=product_raw,
                        amount=None, currency="RUB", payment_status="confirmed", review_status="pending"))
                    stats["historical_payments"] += 1

        db.flush()
        buyers = db.execute(text("SELECT DISTINCT user_id FROM payments WHERE payment_status IN ('paid','confirmed') AND user_id IS NOT NULL")).scalars().all()
        for user_id in buyers:
            user = db.get(User, user_id)
            has_email = db.scalar(select(UserEmail.id).where(UserEmail.user_id == user_id)) is not None
            if user and user.access_review_status == "not_required":
                user.access_review_status = "pending" if has_email else "waiting_registration"
                stats["reviews_queued"] += 1
        db.execute(text("UPDATE payments SET review_status='pending' WHERE payment_status='processing'"))
        db.commit()
    return stats


if __name__ == "__main__":
    print(json.dumps(apply(), ensure_ascii=False, sort_keys=True))
