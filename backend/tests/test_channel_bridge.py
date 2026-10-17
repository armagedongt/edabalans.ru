import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.channel_bridge_routes import PREVIEW_POST_URL, router
from app.config import Settings, get_settings


TOKEN = "test-token-not-a-real-bot"


def make_client(token=TOKEN):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite://", telegram_test_bot_token=token
    )
    return TestClient(app)


def signed_data(*, timestamp=None, token=TOKEN, entry_code="preview"):
    values = {
        "auth_date": str(int(time.time()) if timestamp is None else timestamp),
        "user": json.dumps({"id": 1234567, "first_name": "Test"}),
        "start_param": entry_code,
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_preview_is_public_without_login_and_ignores_external_destination():
    client = make_client()
    for path in ("/c", "/c/", "/apps/channel-bridge", "/apps/channel-bridge/"):
        response = client.get(path + "?url=https://example.com")
        assert response.status_code == 200
        assert f'href="{PREVIEW_POST_URL}"' in response.text
        assert "example.com" not in response.text
        assert "{{DESTINATION" not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert "set-cookie" not in response.headers
    assert client.get("/apps/channel-bridge/bridge.js").status_code == 200


def test_verified_telegram_input_only_returns_the_post_and_no_session():
    response = make_client().post(
        "/apps/channel-bridge/verify", json={"init_data": signed_data()}
    )
    assert response.status_code == 200
    assert response.json() == {"destination": PREVIEW_POST_URL, "source": None, "request_write_access": False}
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(("code", "source"), [
    ("ig", "instagram"), ("yt", "youtube"), ("th", "threads"),
    ("pk", "pikabu"), ("dz", "dzen"), ("vk", "vk"), ("tt", "tiktok"),
    ("writepreview", None), ("preview", None), ("unknown", None), ("", None),
])
def test_short_entry_code_resolves_source_and_permission_mode(code, source):
    response = make_client().post(
        "/apps/channel-bridge/verify", json={"init_data": signed_data(entry_code=code)}
    )
    assert response.status_code == 200
    assert response.json() == {
        "destination": PREVIEW_POST_URL,
        "source": source,
        "request_write_access": source is not None or code == "writepreview",
    }


def test_entry_code_must_be_covered_by_telegram_signature():
    response = make_client().post(
        "/apps/channel-bridge/verify",
        json={"init_data": signed_data(entry_code="ig").replace("start_param=ig", "start_param=yt")},
    )
    assert response.status_code == 401


def test_forged_or_expired_identity_cannot_pass_verification():
    client = make_client()
    for data in (
        signed_data(token="wrong-token"),
        signed_data(timestamp=int(time.time()) - 1000),
        signed_data().replace("1234567", "9999999"),
    ):
        assert client.post("/apps/channel-bridge/verify", json={"init_data": data}).status_code == 401


def test_unconfigured_bot_and_oversized_input_fail_without_redirect():
    assert make_client("").post(
        "/apps/channel-bridge/verify", json={"init_data": signed_data()}
    ).status_code == 503
    assert make_client().post(
        "/apps/channel-bridge/verify", json={"init_data": "x" * 8193}
    ).status_code == 422
