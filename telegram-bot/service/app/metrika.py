"""Upload attributable bot starts and confirmed payments to Yandex Metrika."""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TrackingEvent


class MetrikaOfflineClient:
    def __init__(self, token: str, counter_id: int, transport: httpx.BaseTransport | None = None):
        self.token = token
        self.counter_id = counter_id
        self.transport = transport

    @property
    def base_url(self) -> str:
        return (
            "https://api-metrika.yandex.net/management/v1/counter/"
            f"{self.counter_id}/offline_conversions"
        )

    def existing_comments(self) -> set[str]:
        with httpx.Client(timeout=30, transport=self.transport) as client:
            response = client.get(
                f"{self.base_url}/uploadings",
                params={"type": "BASIC", "limit": 10000},
                headers={"Authorization": f"OAuth {self.token}"},
            )
        response.raise_for_status()
        return {
            str(item.get("comment"))
            for item in response.json().get("uploadings", [])
            if item.get("comment")
        }

    def upload(self, csv_content: str, comment: str) -> dict[str, Any]:
        with httpx.Client(timeout=30, transport=self.transport) as client:
            response = client.post(
                f"{self.base_url}/upload",
                params={"type": "BASIC", "comment": comment},
                headers={"Authorization": f"OAuth {self.token}"},
                files={"file": ("offline-conversions.csv", csv_content.encode("utf-8"), "text/csv")},
            )
        response.raise_for_status()
        return response.json().get("uploading", {})


def _conversion(event: TrackingEvent) -> dict[str, str] | None:
    metadata = event.metadata_json or {}
    if metadata.get("metrika_offline"):
        return None
    raw_query = metadata.get("raw_query") or {}
    yclid = str(raw_query.get("yclid") or "").strip()
    if not yclid:
        return None
    if (
        event.event_type == "start_first"
        and metadata.get("is_first_bot_visit", True) is True
    ) or (
        event.event_type == "start_maintenance"
        and metadata.get("is_first_bot_visit") is True
    ):
        target = "bot_start"
        price = currency = ""
    elif event.event_type == "purchase_paid":
        target = "purchase_paid"
        price = str(metadata.get("price") or "")
        currency = str(metadata.get("currency") or "")
    else:
        return None
    occurred_at = event.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return {
        "Yclid": yclid,
        "Target": target,
        "DateTime": str(int(occurred_at.timestamp())),
        "Price": price,
        "Currency": currency,
    }


def _csv_content(rows: list[dict[str, str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=("Yclid", "Target", "DateTime", "Price", "Currency"),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def sync_offline_conversions(
    session: Session,
    client: MetrikaOfflineClient,
    *,
    batch_size: int = 100,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=5)
    candidates = session.scalars(
        select(TrackingEvent)
        .where(
            TrackingEvent.event_type.in_(("start_first", "start_maintenance", "purchase_paid")),
            TrackingEvent.processed_at.is_(None),
            TrackingEvent.occurred_at <= cutoff,
        )
        .order_by(TrackingEvent.occurred_at, TrackingEvent.id)
        .limit(batch_size)
    ).all()
    if not candidates:
        return 0
    existing_comments = client.existing_comments()
    handled = 0
    for event in candidates:
        row = _conversion(event)
        if not row:
            event.processed_at = datetime.now(UTC)
            session.commit()
            continue
        digest = hashlib.sha256(event.id.encode()).hexdigest()[:20]
        comment = f"edabalans-{digest}"
        recovered = comment in existing_comments
        upload = {} if recovered else client.upload(_csv_content([row]), comment)
        marker = {
            "comment": comment,
            "upload_id": upload.get("id"),
            "status": "recovered" if recovered else upload.get("status", "uploaded"),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        event.metadata_json = {**(event.metadata_json or {}), "metrika_offline": marker}
        event.processed_at = datetime.now(UTC)
        session.commit()
        handled += 1
    return handled
