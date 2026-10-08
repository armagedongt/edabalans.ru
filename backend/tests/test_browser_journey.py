import os
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.database import Base, get_db
from app.config import Settings, get_settings
from app.models import User, TelegramTrackingEvent, MessengerAccount, UserAccess, AccountSession
from app.intensive_web_access import issue_access_token
from app.browser_journey_service import (bind_personal, context_id, issue_context, resolve_browser,
    record_browser_event, purge_browser_history, snapshot_for_context, RETENTION)

SECRET = "browser-test-secret"

@pytest.fixture
def browser():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    def db_override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = lambda: Settings(database_url="sqlite://", app_auth_secret=SECRET)
    yield TestClient(app, base_url="https://edabalans.ru"), factory
    app.dependency_overrides.clear()


def person(db, platform="telegram"):
    user = User(status="active", data_origin="native", first_seen_at=datetime.now(timezone.utc))
    db.add(user); db.flush()
    token, _ = issue_access_token(db, user.id, platform)
    db.add(MessengerAccount(user_id=user.id, platform=platform, platform_user_id="test-"+str(user.id), is_deliverable=True, source="fixture"))
    db.flush()
    return user, token


def test_binding_precedes_acceptance_but_events_wait(browser):
    client, factory = browser
    with factory() as db:
        user, token = person(db); uid = user.id; db.commit()
    result = client.post("/api/public/browser-journey", json={"personal_token":token,"event":"page", "page_url":"https://edabalans.ru/intensive", "accepted":False})
    assert result.status_code == 200
    context = result.json()["context"]
    with factory() as db:
        assert snapshot_for_context(db, SECRET, context)["user_id"] == str(uid)
        assert list(db.scalars(select(TelegramTrackingEvent.event_type))) == ["visitor_state"]
        assert db.scalar(select(AccountSession)) is None
        assert db.scalar(select(UserAccess)) is None
    client.post("/api/public/browser-journey", json={"context":context,"event":"page","accepted":True,"page_url":"https://edabalans.ru/intensive?token=private", "attribution":{"utm_source":"yandex", "password":"bad"}})
    with factory() as db:
        event = db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.event_type=="browser_page"))
        assert event.user_id == uid
        assert event.metadata_json["page_url"] == "https://edabalans.ru/intensive"
        assert event.metadata_json["raw_query"] == {"utm_source":"yandex"}
    assert "Max-Age=31536000" in result.headers["set-cookie"]


def test_anonymous_history_bot_return_and_latest_personal_owner(browser):
    _, factory = browser
    with factory() as db:
        row = resolve_browser(db, SECRET, None)
        original_id = row.metadata_json["browser_id"]
        original = issue_context(SECRET, original_id)
        record_browser_event(db,row,"browser_page","https://edabalans.ru/",attribution={"utm_source":"pikabu"})
        a, ta = person(db); b, tb = person(db,"max")
        db.add(TelegramTrackingEvent(id=str(uuid.uuid4()),user_id=a.id,event_type="start_first",
            metadata_json={"browser_context":original,"source_bot":"FixtureBot"},occurred_at=datetime.now(timezone.utc)))
        db.flush()
        returning = resolve_browser(db, SECRET,None)
        assert bind_personal(db, returning, SECRET, token=ta)
        old_event = db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.event_type=="browser_page"))
        assert old_event.user_id == a.id
        assert snapshot_for_context(db,SECRET,issue_context(SECRET,returning.metadata_json["browser_id"]))["source_bot"] == "FixtureBot"
        bind_personal(db,returning,SECRET,token=tb)
        record_browser_event(db,returning,"browser_page","https://edabalans.ru/intensive")
        db.flush()
        events = list(db.scalars(select(TelegramTrackingEvent).where(TelegramTrackingEvent.event_type=="browser_page")))
        assert [item.user_id for item in events] == [a.id,b.id]
        assert db.get(User,a.id).merged_into_user_id is None


def test_cross_root_handoff_joins_anonymous_destination_history(browser):
    client, factory = browser
    with factory() as db:
        user, token = person(db)
        source=resolve_browser(db,SECRET,None); bind_personal(db,source,SECRET,token=token)
        destination=resolve_browser(db,SECRET,None)
        record_browser_event(db,destination,"browser_page","https://похудение-это-есть.рф/")
        transfer=issue_context(SECRET,source.metadata_json["browser_id"],transfer=True)
        target_context=issue_context(SECRET,destination.metadata_json["browser_id"])
        db.commit(); uid=user.id
    origin="https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai"
    assert client.options("/api/public/browser-journey", headers={"Origin":origin,"Access-Control-Request-Method":"POST"}).headers["access-control-allow-origin"]==origin
    response=client.post("/api/public/browser-journey",headers={"Origin":origin},json={"context":target_context,"transfer":transfer})
    assert response.status_code==200
    assert set(response.json())=={"context","transfer"}
    with factory() as db:
        assert snapshot_for_context(db,SECRET,response.json()["context"])["user_id"]==str(uid)
        assert db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.event_type=="browser_page")).user_id==uid
    assert client.post("/api/public/browser-journey",headers={"Origin":"https://evil.test"},json={}).status_code==403
    assert context_id(SECRET,transfer) is None
    assert context_id("wrong",target_context) is None


def test_retention_preserves_business_and_bot_history(browser):
    _, factory=browser
    with factory() as db:
        old=datetime.now(timezone.utc)-RETENTION-timedelta(seconds=1)
        user,token=person(db)
        row=resolve_browser(db,SECRET,None); row.occurred_at=old
        context=issue_context(SECRET,row.metadata_json["browser_id"])
        db.add(TelegramTrackingEvent(id=str(uuid.uuid4()),user_id=user.id,event_type="start_first",occurred_at=old))
        db.add(TelegramTrackingEvent(id=str(uuid.uuid4()),event_type="browser_page",occurred_at=old))
        db.flush()
        assert snapshot_for_context(db,SECRET,context) is None
        assert purge_browser_history(db)==2
        assert db.scalar(select(TelegramTrackingEvent.event_type))=="start_first"
        assert db.get(User,user.id) is not None
