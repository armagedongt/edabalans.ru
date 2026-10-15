import copy
import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import travel_service as s
from app.travel_routes import router, TravelBodyLimit
from app.config import get_settings


def model():
    return {"title": "Synthetic trip", "settings": {k: 1000 for k in s.SETTINGS} | {"restaurantFrequency": 2},
            "returnFlight": {"from": "B", "amount": 100}, "phases": [{"id": "one", "title": "A", "country": "B", "start": "2027-01-01", "end": "2027-01-03", "base": True, "nightRate": 100, "flight": {"from": "B", "amount": 100}, "items": []}]}


def files(m=None, body="## overview | Overview\nHello"):
    m = m or model()
    plan = {k: m[k] for k in ("title", "settings", "returnFlight")}
    plan["phaseIds"] = [p["id"] for p in m["phases"]]
    return {"plan.md": s.document(plan, "# Plan"), "phases/one.md": s.document(m["phases"][0], body)}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "ROOT", tmp_path / "private")
    get_settings.cache_clear()
    s.publish(files(), "")
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(TravelBodyLimit)
    return TestClient(app, base_url="https://example.test")


AUTH = ("admin@example.com", "test-admin-password")
HEADERS = {"X-Travel-Write": "1"}


def test_data_and_assets_are_private(client):
    assert client.get("/admin/api/travel/plan").status_code == 401
    assert client.get("/admin/travel/assets/app.mjs").status_code == 401
    assert client.get("/admin/travel", follow_redirects=False).status_code == 303
    r = client.get("/admin/api/travel/plan", auth=AUTH)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"


def test_edit_persists_to_markdown_and_stale_revision_cannot_overwrite(client):
    data = client.get("/admin/api/travel/plan", auth=AUTH).json()
    data["model"]["phases"][0]["nightRate"] = 777
    r = client.put("/admin/api/travel/plan", auth=AUTH, headers=HEADERS, json=data)
    assert r.status_code == 200
    assert "777" in s.snapshot()[0]["phases/one.md"]
    assert client.put("/admin/api/travel/plan", auth=AUTH, headers=HEADERS, json=data).status_code == 409
    assert client.get("/admin/api/travel/plan", auth=AUTH).json()["model"]["phases"][0]["nightRate"] == 777


def test_markdown_publish_rejects_traversal_and_cross_origin(client):
    revision = s.snapshot()[1]
    bad = files() | {"../private.md": "secret"}
    assert client.post("/admin/api/travel/publish", auth=AUTH, headers=HEADERS, json={"revision": revision, "files": bad}).status_code == 422
    r = client.post("/admin/api/travel/publish", auth=AUTH, headers=HEADERS | {"Origin": "https://evil.test"}, json={"revision": revision, "files": files()})
    assert r.status_code == 403
    assert s.snapshot()[1] == revision


def test_markdown_html_and_dangerous_links_cannot_execute(client):
    s.publish(files(body='## overview | Safe\n<script>alert(1)</script>\n\n[bad](javascript:alert(2))\n\n[good](https://example.org/)'), s.snapshot()[1])
    body = client.get("/admin/api/travel/phases/one", auth=AUTH).json()["sections"][0]["html"]
    assert "<script>" not in body
    assert 'href="javascript:' not in body
    assert 'href="https://example.org/"' in body


@pytest.mark.parametrize("change", [lambda m: m["phases"][0].update(nightRate=-1), lambda m: m["phases"][0].update(end="2026-01-01"), lambda m: m["phases"][0].update(items=[1])])
def test_invalid_edits_do_not_mutate_current(client, change):
    data = client.get("/admin/api/travel/plan", auth=AUTH).json()
    revision = data["revision"]
    change(data["model"])
    assert client.put("/admin/api/travel/plan", auth=AUTH, headers=HEADERS, json=data).status_code == 422
    assert s.snapshot()[1] == revision


def test_unknown_price_marker_survives_publish(client):
    m = model()
    m["phases"][0]["items"] = [{"id": "bike", "title": "Unknown bicycle handling", "bucket": "sport", "amount": 0, "selected": True, "unknown": True}]
    s.publish(files(m), s.snapshot()[1])
    assert client.get("/admin/api/travel/plan", auth=AUTH).json()["model"]["phases"][0]["items"][0]["unknown"] is True


def test_large_body_is_rejected_before_parsing(client):
    r = client.post("/admin/api/travel/publish", auth=AUTH, headers=HEADERS | {"Content-Type": "application/json"}, content=b"x" * (s.MAX_BYTES + 200001))
    assert r.status_code == 413

def test_compact_iso_dates_rejected_before_publish(client):
    data = client.get('/admin/api/travel/plan', auth=AUTH).json()
    data['model']['phases'][0].update(start='20270101', end='20270103')
    assert client.put('/admin/api/travel/plan', auth=AUTH, headers=HEADERS, json=data).status_code == 422
    assert s.snapshot()[1] == data['revision']

def test_markdown_export_is_private_and_restores(client, tmp_path, monkeypatch):
    assert client.get('/admin/api/travel/export').status_code == 401
    exported = client.get('/admin/api/travel/export', auth=AUTH).json()
    original = s.compile_files(exported['files'])
    monkeypatch.setattr(s, 'ROOT', tmp_path / 'restored')
    s.publish(exported['files'], '')
    assert s.compile_files(s.snapshot()[0]) == original
