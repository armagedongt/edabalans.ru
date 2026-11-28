import io
import base64
import os
import shutil
import uuid
import wave
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.account_auth_routes import ACCOUNT_MANAGER_EMAIL, ACCOUNT_VIEW_HEADER, COOKIE_NAME
from app.account_security import token_hash
from app.database import Base, get_db
from app import masterclass_discussion as discussion
from app import masterclass_discussion_push as push
from app.models import AccountCredential, AccountSession, MasterclassDiscussionPost, User, UserEmail

BASE = discussion.router.prefix
ORIGIN = "https://testserver"


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    settings = SimpleNamespace(masterclass_discussion_pilot=True, masterclass_discussion_media_dir=str(tmp_path))
    monkeypatch.setattr(discussion, "get_settings", lambda: settings)
    monkeypatch.setattr(push, "get_settings", lambda: settings)
    engine = create_engine("sqlite://", connect_args={"check_same_thread":False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(push, "SessionLocal", factory)
    with factory.begin() as db:
        for name, email in (("owner", ACCOUNT_MANAGER_EMAIL), ("member", "member@example.test"),
                            ("manager", "manager@example.test")):
            user = User(display_name=name, status="active")
            db.add(user)
            db.flush()
            db.add(UserEmail(user_id=user.id, email_original=email, email_normalized=email,
                             is_primary=True, source="test"))
            db.add(AccountCredential(user_id=user.id, password_hash="unused", password_version=1, issued_via="test"))
            db.add(AccountSession(
                user_id=user.id, token_hash=token_hash(name), password_version=1,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            ))
        db.add(MasterclassDiscussionPost(day_number=4, client_nonce="fixture", source_label="Учебный пример",
                                        body="Как отметить блюдо?", archived=True))

    app = FastAPI()
    app.include_router(discussion.router)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database

    def client(name=None):
        result = TestClient(app, base_url=ORIGIN, headers={"Origin":ORIGIN})
        if name:
            result.cookies.set(COOKIE_NAME, name)
        return result

    yield client, factory, settings
    engine.dispose()


def test_pilot_allows_only_direct_owner(pilot):
    client, factory, settings = pilot
    for name in (None, "member", "manager"):
        other = client(name)
        status = other.get(BASE + "/status").json()
        assert status == {"mode":"locked","notice":discussion.NOTICE}
        assert other.get(BASE + "/thread").status_code == 403
        assert other.get(BASE + "/posts/1/photo").status_code == 403
        assert other.post(BASE + "/read", json={"ids":[1]}).status_code == 403
    with factory() as db:
        member = db.scalar(select(User).where(User.display_name == "member"))
    direct = client("owner")
    assert direct.get(BASE + "/thread", headers={ACCOUNT_VIEW_HEADER:str(member.id)}).status_code == 403
    assert direct.get(BASE + "/status").json() == {"mode":"owner","unread":1,"total":1}
    assert direct.post(BASE + "/read", headers={"Origin":"https://elsewhere.test"}, json={"ids":[1]}).status_code == 403
    settings.masterclass_discussion_pilot = False
    assert direct.get(BASE + "/status").json() == {"mode":"off"}
    assert direct.get(BASE + "/thread").status_code == 403


def test_marked_reply_is_one_post_and_read_is_idempotent(pilot):
    client, _, _ = pilot
    owner = client("owner")
    data = {"nonce":str(uuid.uuid4()),"text":"Ответ к вопросу","reply_to":1,"featured":"true"}
    response = owner.post(BASE + "/posts", data=data)
    assert response.status_code == 200, response.text
    answer = response.json()["posts"][-1]
    assert answer["marked"] and answer["replyTo"] == 1
    assert owner.post(BASE + "/posts", data=data).json()["posts"][-1]["id"] == answer["id"]
    thread = owner.get(BASE + "/thread").json()
    assert len(thread["posts"]) == thread["total"] == 2
    assert thread["answers"] == {"1":answer["id"]}
    assert thread["firstUnread"] == 1 and thread["unread"] == 1
    new = owner.post(BASE + "/posts", data=dict(data, nonce=str(uuid.uuid4()), text="Новый ответ")).json()
    assert new["answers"]["1"] != answer["id"]
    older = next(post for post in owner.get(BASE + "/thread").json()["posts"] if post["id"] == answer["id"])
    assert not older["marked"]
    for _ in range(2):
        assert owner.post(BASE + "/read", json={"ids":[1, answer["id"], 999]}).json() == {"unread":0}


def test_paginated_thread_counts_all_posts_and_finds_first_unread(pilot):
    client, factory, _ = pilot
    owner = client("owner")
    with factory.begin() as db:
        db.add_all(MasterclassDiscussionPost(day_number=4, client_nonce=f"old-{number}", body="Архив", archived=True)
                   for number in range(discussion.PAGE_SIZE))
    assert owner.post(BASE + "/read", json={"ids":[1]}).status_code == 200
    thread = owner.get(BASE + "/thread").json()
    assert len(thread["posts"]) == discussion.PAGE_SIZE
    assert thread["total"] == discussion.PAGE_SIZE + 1 and thread["more"]
    assert thread["firstUnread"] == 2


def test_profile_and_private_photo_are_bound_to_native_account(pilot):
    client, _, _ = pilot
    owner = client("owner")
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buffer, "PNG")
    picture = ("image.png", buffer.getvalue(), "image/png")
    profile = owner.put(BASE + "/profile", data={"name":"Сергей","about":"Мой профиль","visible":"true"},
                        files={"photo":picture}).json()["profile"]
    assert profile["name"] == "Сергей" and profile["about"] == "Мой профиль"
    assert client("member").get(profile["avatar"]).status_code == 403
    assert owner.get(profile["avatar"]).headers["content-type"] == "image/webp"
    entry = owner.post(BASE + "/posts", data={"nonce":str(uuid.uuid4())}, files={"photo":picture}).json()["posts"][0]
    content = owner.get(entry["photo"], headers={"Range":"bytes=0-9"})
    assert content.status_code == 206 and len(content.content) == 10
    assert content.headers["cache-control"] == "private, no-store"
    assert client("member").get(entry["photo"]).status_code == 403
    assert owner.put(BASE + "/profile", data={"name":"Сергей","visible":"false"}).json()["profile"] is None
    assert owner.get(profile["avatar"]).status_code == 404
    removed = owner.put(BASE + "/profile", data={"name":"Сергей","visible":"true","remove_photo":"true"})
    assert removed.json()["avatar"] is None
    assert owner.get(profile["avatar"]).status_code == 404


def test_empty_display_name_has_stable_two_word_alias(pilot):
    client, _, _ = pilot
    owner = client("owner")
    names = []
    for about in ("Первое описание", "Другое описание"):
        saved = owner.put(BASE + "/profile", data={"name":"", "about":about, "visible":"true"})
        assert saved.status_code == 200
        names.append(saved.json()["profile"]["name"])
    assert names[0] == names[1]
    assert len(names[0].split()) == 2
    assert names[0] != "Сергей Воронцов"


def test_posts_from_participants_without_profiles_have_distinct_aliases(pilot):
    client, factory, _ = pilot
    with factory.begin() as db:
        for number in (1, 2):
            user = User(id=uuid.UUID(int=number), display_name=f"Имя из аккаунта {number}", status="active")
            db.add(user)
            db.flush()
            db.add(MasterclassDiscussionPost(day_number=4, author_id=user.id, client_nonce=f"alias-{number}",
                                              body=f"Вопрос {number}", archived=False))
    owner = client("owner")
    entries = owner.get(BASE + "/thread").json()["posts"]
    aliases = [entry["name"] for entry in entries if entry["text"].startswith("Вопрос ")]
    assert len(set(aliases)) == 2 and all(len(name.split()) == 2 for name in aliases)
    assert owner.get(BASE + "/thread").json()["posts"] == entries
    assert entries[0]["name"] == "Учебный пример"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="audio conversion is installed in target image")
def test_voice_transcodes_and_supports_ranges(pilot):
    client, _, _ = pilot
    owner = client("owner")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        out.writeframes(b"\x10\x02" * 16000)
    sample = ("test.wav", buffer.getvalue(), "audio/wav")
    preview = owner.post(BASE + "/voice-preview", files={"voice":sample})
    assert preview.status_code == 200 and preview.headers["content-type"] == "audio/mpeg"
    answer = owner.post(BASE + "/posts", data={"nonce":str(uuid.uuid4())}, files={"voice":sample})
    assert answer.status_code == 200, answer.text
    uri = answer.json()["posts"][0]["voice"]
    assert owner.get(uri, headers={"Range":"bytes=0-31"}).status_code == 206
    assert client("member").get(uri).status_code == 403


def test_webpush_checks_provider_and_delivers_synchronously_in_test_queue(pilot, monkeypatch):
    client, _, _ = pilot
    owner = client("owner")
    config = owner.post(BASE + "/push/key")
    assert config.status_code == 200 and len(config.json()["key"]) == 87
    keys = {"p256dh":config.json()["key"], "auth":base64.urlsafe_b64encode(b"1" * 16).decode().rstrip("=")}
    body = {"endpoint":"https://localhost/push","keys":keys,"replies":True,"new_posts":False}
    assert owner.put(BASE + "/push/subscription", json=body).status_code == 422
    body["endpoint"] = "https://fcm.googleapis.com/fcm/send/test"
    assert owner.put(BASE + "/push/subscription", json=body).status_code == 200
    endpoint = {"endpoint":body["endpoint"]}
    options = owner.post(BASE + "/push/preferences", json=endpoint).json()
    assert options == {"enabled":True,"replies":True,"new_posts":False}
    message = {"endpoint":body["endpoint"],"kind":"reply","nonce":str(uuid.uuid4())}
    assert client("member").post(BASE + "/push/test", json=message).status_code == 403
    for _ in range(2):
        assert owner.post(BASE + "/push/test", json=message).status_code == 200
    sent = []
    monkeypatch.setattr(push, "webpush", lambda **kwargs: sent.append(kwargs))
    assert push.deliver_one()
    assert len(sent) == 1 and "discussion_post=1" in sent[0]["data"]
    assert not push.deliver_one()
    other_endpoint = {"endpoint":"https://fcm.googleapis.com/fcm/send/other-device"}
    assert owner.put(BASE + "/push/subscription", json=dict(body, **other_endpoint)).status_code == 200
    assert owner.put(BASE + "/push/subscription", json=dict(body, replies=False, new_posts=True)).status_code == 200
    assert owner.post(BASE + "/push/preferences", json=endpoint).json() == {
        "enabled":True,"replies":False,"new_posts":True,
    }
    assert owner.request("DELETE", BASE + "/push/subscription", json=endpoint).status_code == 200
    defaults = owner.post(BASE + "/push/preferences", json=endpoint).json()
    assert defaults == {"enabled":False,"replies":True,"new_posts":True}
    assert owner.post(BASE + "/push/preferences", json=other_endpoint).json() == options
