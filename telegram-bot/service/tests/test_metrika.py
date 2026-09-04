from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.metrika import sync_offline_conversions
from app.metrika import MetrikaOfflineClient
import httpx
from app.models import TrackingEvent


class FakeMetrika:
    def __init__(self, comments=()):
        self.comments = set(comments)
        self.uploads = []

    def existing_comments(self):
        return self.comments

    def upload(self, csv_content, comment):
        self.uploads.append((csv_content, comment))
        return {"id": 77, "status": "UPLOADED"}


def make_session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'metrika.sqlite'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_sync_uploads_first_start_and_paid_amount_once(tmp_path):
    now = datetime.now(UTC)
    with make_session(tmp_path) as session:
        session.add_all([
            TrackingEvent(
                id="start-1",
                event_type="start_first",
                metadata_json={"raw_query": {"yclid": "click-1"}},
                occurred_at=now - timedelta(minutes=2),
            ),
            TrackingEvent(
                id="paid-1",
                event_type="purchase_paid",
                metadata_json={
                    "raw_query": {"yclid": "click-1"},
                    "price": "4990.00",
                    "currency": "RUB",
                },
                occurred_at=now - timedelta(minutes=1),
            ),
            TrackingEvent(
                id="start-organic",
                event_type="start_first",
                metadata_json={"raw_query": {}},
                occurred_at=now - timedelta(minutes=1),
            ),
        ])
        session.commit()
        client = FakeMetrika()

        assert sync_offline_conversions(session, client, now=now) == 2
        assert sync_offline_conversions(session, client, now=now) == 0
        assert len(client.uploads) == 2
        start_row = list(csv.DictReader(io.StringIO(client.uploads[0][0])))[0]
        paid_row = list(csv.DictReader(io.StringIO(client.uploads[1][0])))[0]
        assert start_row == {
            "Yclid": "click-1",
            "Target": "bot_start",
            "DateTime": str(int((now - timedelta(minutes=2)).timestamp())),
            "Price": "",
            "Currency": "",
        }
        assert paid_row == {
            "Yclid": "click-1",
            "Target": "purchase_paid",
            "DateTime": str(int((now - timedelta(minutes=1)).timestamp())),
            "Price": "4990.00",
            "Currency": "RUB",
        }
        events = session.scalars(select(TrackingEvent).where(
            TrackingEvent.id.in_(("start-1", "paid-1"))
        )).all()
        assert all(event.metadata_json["metrika_offline"]["upload_id"] == 77 for event in events)


def test_first_maintenance_start_is_uploaded_but_repeat_is_not(tmp_path):
    now = datetime.now(UTC)
    with make_session(tmp_path) as session:
        session.add_all([
            TrackingEvent(
                id="maintenance-first",
                event_type="start_maintenance",
                metadata_json={
                    "raw_query": {"yclid": "maintenance-click"},
                    "is_first_bot_visit": True,
                },
                occurred_at=now - timedelta(minutes=2),
            ),
            TrackingEvent(
                id="maintenance-repeat",
                event_type="start_maintenance",
                metadata_json={
                    "raw_query": {"yclid": "maintenance-click-2"},
                    "is_first_bot_visit": False,
                },
                occurred_at=now - timedelta(minutes=1),
            ),
        ])
        session.commit()
        client = FakeMetrika()

        assert sync_offline_conversions(session, client, now=now) == 1
        assert len(client.uploads) == 1
        row = list(csv.DictReader(io.StringIO(client.uploads[0][0])))[0]
        assert row["Target"] == "bot_start"
        assert session.get(TrackingEvent, "maintenance-repeat").processed_at is not None


def test_sync_recovers_after_accepted_upload_without_reposting(tmp_path):
    now = datetime.now(UTC)
    with make_session(tmp_path) as session:
        event = TrackingEvent(
            id="recover-1",
            event_type="start_first",
            metadata_json={"raw_query": {"yclid": "click-recover"}},
            occurred_at=now - timedelta(minutes=1),
        )
        session.add(event)
        session.commit()
        probe = FakeMetrika()
        sync_offline_conversions(session, probe, now=now)
        comment = probe.uploads[0][1]
        event.metadata_json = {"raw_query": {"yclid": "click-recover"}}
        event.processed_at = None
        session.commit()
        recovered = FakeMetrika({comment})

        assert sync_offline_conversions(session, recovered, now=now) == 1
        assert recovered.uploads == []
        assert event.metadata_json["metrika_offline"]["status"] == "recovered"


def test_failed_upload_keeps_conversion_pending_for_next_sync(tmp_path):
    now = datetime.now(UTC)

    class FailOnceMetrika(FakeMetrika):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def upload(self, csv_content, comment):
            self.attempts += 1
            if self.attempts == 1:
                raise httpx.ConnectError("temporary Yandex failure")
            return super().upload(csv_content, comment)

    with make_session(tmp_path) as session:
        event = TrackingEvent(
            id="retry-after-failure",
            event_type="start_first",
            metadata_json={"raw_query": {"yclid": "click-retry"}},
            occurred_at=now - timedelta(minutes=1),
        )
        session.add(event)
        session.commit()
        client = FailOnceMetrika()

        try:
            sync_offline_conversions(session, client, now=now)
        except httpx.ConnectError:
            pass
        else:
            raise AssertionError("the first upload must fail")

        session.refresh(event)
        assert event.processed_at is None
        assert "metrika_offline" not in event.metadata_json
        assert sync_offline_conversions(session, client, now=now) == 1
        assert len(client.uploads) == 1
        assert event.processed_at is not None


def test_real_client_uses_yandex_contract_for_listing_and_upload():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api-metrika.yandex.net"
        assert request.url.path.startswith(
            "/management/v1/counter/97331502/offline_conversions/"
        )
        assert request.headers["authorization"] == "OAuth secret-token"
        if request.url.path.endswith("/uploadings"):
            return httpx.Response(200, json={"uploadings": [{"comment": "existing-1"}]})
        assert request.url.path.endswith("/upload")
        assert request.url.params["type"] == "BASIC"
        assert request.url.params["comment"] == "batch-1"
        assert "multipart/form-data" in request.headers["content-type"]
        assert b"offline-conversions.csv" in request.content
        assert b"Yclid,Target,DateTime,Price,Currency" in request.content
        return httpx.Response(200, json={"uploading": {"id": 42, "status": "UPLOADED"}})

    client = MetrikaOfflineClient(
        "secret-token",
        97331502,
        transport=httpx.MockTransport(handler),
    )

    assert client.existing_comments() == {"existing-1"}
    assert client.upload("Yclid,Target,DateTime,Price,Currency\n1,bot_start,1,,\n", "batch-1") == {
        "id": 42,
        "status": "UPLOADED",
    }
    assert len(requests) == 2
