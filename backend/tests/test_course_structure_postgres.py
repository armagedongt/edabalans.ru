"""Opt-in proof against a separately created, disposable PostgreSQL database."""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import User, MasterclassStepProgress
from app import course_structure_service as native
from app.course_structure_lock import KEYS, check_structure, lock_course
from app.course_structure_operations import apply
from app.managed_documents import document_hash
from app.models import AccountCredential, AccountSession
from app.account_security import token_hash
from starlette.requests import Request

URL = os.environ.get("EDABALANS_STRUCTURE_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="Requires a disposable PostgreSQL structure database")


@pytest.fixture
def database():
    parsed = make_url(URL)
    assert parsed.drivername.startswith("postgresql")
    assert parsed.database.startswith("editorial_structure_test_"), "Never run against application data"
    engine = create_engine(URL)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory() as db:
            context = native.course_context(db)
            manifest = deepcopy(context.manifest)
            manifest["days"][0]["steps"] = [{"id": "a", "kind": "article", "title": "Первая"},
                                           {"id": "b", "kind": "article", "title": "Вторая"}]
            context.revision.payload = manifest
            context.revision.content_hash = document_hash(manifest)
            user = User(display_name="Isolated structure test", status="active")
            db.add(user)
            db.commit()
            user_id = user.id
        yield factory, user_id
    finally:
        # Model metadata contains unnamed cyclic constraints; disposable schema only.
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()


def wait_for_advisory_waiter(factory):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with factory() as db:
            blocked = db.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=:key AND NOT granted"),
                                {"key": KEYS["masterclass-21"]})
        if blocked:
            return
        time.sleep(.05)
    pytest.fail("The concurrent operation never waited on the course advisory lock")


def test_learner_shared_lock_precedes_user_lock_and_writer_remaps_committed_mark(database):
    factory, user_id = database
    held = threading.Event()
    release = threading.Event()
    def learner():
        with factory() as db:
            lock_course(db, "masterclass-21")
            db.execute(select(User.id).where(User.id == user_id).with_for_update())
            context = native.course_context(db)
            assert context.revision.version_no == 1
            held.set()
            assert release.wait(10)
            db.add(MasterclassStepProgress(user_id=user_id, day_number=1, step_index=0,
                                          step_id="a", step_kind="article"))
            db.commit()
    def writer():
        with factory() as db:
            return apply(db, "masterclass-21", 1, {"type": "reorder", "unit": 1, "ids": ["b", "a"]}, "isolated-test")
    with ThreadPoolExecutor(2) as pool:
        learning = pool.submit(learner)
        assert held.wait(10)
        publishing = pool.submit(writer)
        try:
            wait_for_advisory_waiter(factory)
            assert not publishing.done()
        finally:
            release.set()
        learning.result(timeout=10)
        assert publishing.result(timeout=10)["version"] == 2
    with factory() as db:
        row = db.scalar(select(MasterclassStepProgress))
        assert (row.step_id, row.day_number, row.step_index) == ("a", 1, 1)


def test_writer_exclusive_lock_blocks_old_learner_before_user_and_stale_action_has_no_mark(database):
    factory, user_id = database
    held = threading.Event()
    release = threading.Event()
    def writer():
        with factory() as db:
            lock_course(db, "masterclass-21", exclusive=True)
            held.set()
            assert release.wait(10)
            return apply(db, "masterclass-21", 1, {"type": "reorder", "unit": 1, "ids": ["b", "a"]}, "isolated-test")
    def learner():
        with factory() as db:
            lock_course(db, "masterclass-21")
            db.execute(select(User.id).where(User.id == user_id).with_for_update())
            context = native.course_context(db)
            with pytest.raises(HTTPException) as error:
                check_structure(context.manifest, context.revision.version_no,
                                SimpleNamespace(structure_version=1, step_id="a"), step=context.days[1]["steps"][0])
            assert error.value.status_code == 409
    with ThreadPoolExecutor(2) as pool:
        publishing = pool.submit(writer)
        assert held.wait(10)
        learning = pool.submit(learner)
        try:
            wait_for_advisory_waiter(factory)
            assert not learning.done()
        finally:
            release.set()
        assert publishing.result(timeout=10)["version"] == 2
        learning.result(timeout=10)
    with factory() as db:
        assert db.scalar(select(MasterclassStepProgress)) is None


def test_two_concurrent_structural_writers_accept_exactly_one_revision(database):
    factory, _ = database
    start = threading.Barrier(2)
    def writer():
        with factory() as db:
            start.wait(timeout=10)
            try:
                apply(db, "masterclass-21", 1, {"type": "reorder", "unit": 1, "ids": ["b", "a"]}, "isolated-test")
                return 200
            except HTTPException as error:
                return error.status_code
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(writer) for _ in range(2)]
        assert sorted(future.result(timeout=15) for future in futures) == [200, 409]
    with factory() as db:
        assert native.active_course_version(db).version_no == 2


@pytest.mark.parametrize("course", ["masterclass-21", "recipes", "calories"])
def test_actual_resolver_retains_lock_after_hourly_native_session_commit(database, monkeypatch, course):
    factory,user_id=database
    from app import masterclass_routes as mk, recipe_course_routes as recipes, calorie_course_routes as calorie
    from app.config import Settings
    module={"masterclass-21":mk,"recipes":recipes,"calories":calorie}[course]
    # Product rights are covered by native journeys; preserve actual cookie-session read/commit.
    monkeypatch.setattr(module,"require_user_resource",lambda db,user,*args:user)
    if course=="masterclass-21":
        monkeypatch.setattr(mk,"course_start_is_open",lambda *args:True)
        monkeypatch.setattr(mk,"access_codes",lambda *args:{"ACCESS_MASTERCLASS"})
    elif course=="recipes":
        monkeypatch.setattr(recipes,"course_start_is_open",lambda *args:True)
    else:
        monkeypatch.setattr(calorie,"course_waits_for_consultation",lambda *args:False)
        monkeypatch.setattr(calorie,"course_entry_unlocked",lambda *args:True)
        monkeypatch.setattr(calorie,"publication_status",lambda *args:{"ready":True})
    now=datetime.now(timezone.utc)
    with factory() as db:
        db.add(AccountCredential(user_id=user_id,password_hash="unused",password_version=1,issued_via="test"))
        db.add(AccountSession(user_id=user_id,token_hash=token_hash("isolated-cookie"),password_version=1,
                              expires_at=now+timedelta(days=1),last_seen_at=now-timedelta(hours=2)))
        db.commit()
    request=Request({"type":"http","method":"POST","path":"/","headers":[
                     (b"cookie",b"edabalans_account_session=isolated-cookie")]})
    held=threading.Event();release=threading.Event()
    code="calories" if course=="calories" else "masterclass-21"
    def learner():
        with factory() as db:
            if course=="masterclass-21": mk.resolve_masterclass_user(request,db,"",Settings(database_url=URL))
            elif course=="recipes": recipes.resolve_course_user(request,db)
            else: calorie.resolve_course_user(request,db,"")
            db.execute(select(User.id).where(User.id==user_id).with_for_update())
            held.set()
            assert release.wait(10)
            db.commit()
    def writer():
        with factory() as db:
            lock_course(db,code,exclusive=True)
            db.commit()
    with ThreadPoolExecutor(2) as pool:
        learning=pool.submit(learner)
        assert held.wait(10)
        publishing=pool.submit(writer)
        try:
            deadline=time.monotonic()+5
            blocked=0
            while time.monotonic()<deadline:
                with factory() as db:
                    blocked=db.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=:key AND NOT granted"),{"key":KEYS[code]})
                if blocked: break
                time.sleep(.05)
            assert blocked and not publishing.done(),"Actual resolver released the course transaction guard"
        finally: release.set()
        learning.result(timeout=10);publishing.result(timeout=10)
    with factory() as db:
        session=db.scalar(select(AccountSession))
        assert session.last_seen_at>now-timedelta(minutes=1),"Real native-session hourly commit was not exercised"
