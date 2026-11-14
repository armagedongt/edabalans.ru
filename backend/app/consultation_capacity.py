"""Shared availability for the direct consultation checkout."""
from datetime import datetime, timedelta
import random

from sqlalchemy import text

from app.managed_documents import active_document, document_hash
from app.models import ManagedDocumentVersion

CAPACITY_TYPE = "consultation-capacity"
CAPACITY_KEY = "homepage"
# Separate from pricing, payment and course locks. Always held to transaction end.
CAPACITY_LOCK = 694128103


def _capacity_lock(db):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CAPACITY_LOCK})


def _delay(places):
    if places == 0:
        return timedelta(minutes=5)
    if places == 1:
        return timedelta(minutes=30)
    return timedelta(hours=random.choice((1, 6, 24)))


def _state(db, now):
    _capacity_lock(db)
    row = active_document(db, CAPACITY_TYPE, CAPACITY_KEY)
    if row is None:
        payload = {"places": 2, "next_at": (now + _delay(2)).isoformat()}
        row = ManagedDocumentVersion(document_type=CAPACITY_TYPE, document_key=CAPACITY_KEY,
                                     schema_version=1, version_no=1, payload=payload,
                                     content_hash=document_hash(payload), created_by="system", is_active=True)
        db.add(row)
        db.flush()
    places = row.payload["places"]
    next_at = datetime.fromisoformat(row.payload["next_at"])
    if now >= next_at:
        if places < 2:
            places += 1
        else:
            places = random.choice([n for n in range(2, 5) if abs(n - places) == 1])
        _save(row, places, now)
    return row, places


def _save(row, places, now):
    payload = {"places": places, "next_at": (now + _delay(places)).isoformat()}
    row.payload = payload
    row.content_hash = document_hash(payload)


def available_consultations(db, now: datetime, *, commit=True):
    _, places = _state(db, now)
    if commit:
        db.commit()
    return places


def confirm_consultation(db, now: datetime):
    row, places = _state(db, now)
    _save(row, max(places - 1, 0), now)
