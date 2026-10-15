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


def test_public_view_and_private_admin_operations(client):
    for path in ["/travel", "/travel/phases/one", "/travel/assets/app.mjs", "/api/travel/phases/one"]:
        assert client.get(path).status_code == 200
    public = client.get("/api/travel/plan")
    assert public.status_code == 200
    assert public.json()["canEdit"] is False
    assert public.headers["cache-control"] == "no-store"
    assert public.headers["x-robots-tag"] == "noindex, nofollow"
    assert "files" not in public.json()
    assert client.get("/api/travel/plan", auth=AUTH).json()["canEdit"] is True
    assert client.get("/admin/api/travel/plan").status_code == 401
    assert client.get("/admin/api/travel/export").status_code == 401
    assert client.get("/admin/travel", follow_redirects=False).headers["location"] == "/travel"
    assert client.get("/admin/travel/phases/one", follow_redirects=False).headers["location"] == "/travel/phases/one"


def test_admin_cookie_enables_main_editor(client):
    from app.auth import admin_session_token, ADMIN_COOKIE
    import time
    client.cookies.set(ADMIN_COOKIE, admin_session_token(AUTH[0], int(time.time()) + 60))
    assert client.get("/api/travel/plan").json()["canEdit"] is True


def test_public_cannot_write_even_with_forged_editor_flag(client):
    before = s.snapshot()[1]
    data = client.get("/api/travel/plan").json()
    data["canEdit"] = True
    data["model"]["settings"]["shopping"] = 999
    assert client.put("/admin/api/travel/plan", headers=HEADERS, json=data).status_code == 401
    assert client.post("/admin/api/travel/publish", headers=HEADERS, json={"files": files(), "revision": before}).status_code == 401
    assert client.put("/api/travel/plan", headers=HEADERS, json=data).status_code == 405
    assert s.snapshot()[1] == before


def test_phase_program_is_changed_by_markdown_not_main_editor(client):
    data = client.get("/api/travel/plan", auth=AUTH).json()
    item = {"id": "ticket", "title": "A ticket", "bucket": "fixed", "amount": 100, "selected": True}
    data["model"]["phases"][0]["items"] = [item]
    assert client.put("/admin/api/travel/plan", auth=AUTH, headers=HEADERS, json=data).status_code == 422
    assert s.snapshot()[1] == data["revision"]
    published = client.post("/admin/api/travel/publish", auth=AUTH, headers=HEADERS, json={"files": files(data["model"]), "revision": data["revision"]})
    assert published.status_code == 200
    assert client.get("/api/travel/plan").json()["model"]["phases"][0]["items"][0]["amount"] == 100


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


def guide():
    return {"places": [{"id": "hotel", "name": "Synthetic hotel", "category": "hotel", "latitude": 13.7,
                        "longitude": 100.6, "section": "housing", "number": 1}], "routes": [],
            "hotels": [{"placeId": "hotel", "half": "first", "role": "First", "breakfast": "unknown",
                        "bookingURL": "https://www.booking.com/hotel/test.html", "quotedTotal": 1200,
                        "quotedStart": "2027-01-01", "quotedEnd": "2027-01-03", "quoteSource": "Owner"}]}


def test_guide_is_public_readable_but_immutable_from_main_editor(client):
    m = model()
    m["phases"][0]["guide"] = guide()
    s.publish(files(m), s.snapshot()[1])
    response = client.get("/api/travel/phases/one")
    assert response.status_code == 200
    assert response.json()["phase"]["guide"]["places"][0]["latitude"] == 13.7
    data = client.get("/api/travel/plan", auth=AUTH).json()
    data["model"]["phases"][0]["guide"]["places"][0]["latitude"] = 14
    assert client.put("/admin/api/travel/plan", auth=AUTH, headers=HEADERS, json=data).status_code == 422
    assert s.snapshot()[1] == data["revision"]


@pytest.mark.parametrize("change", [
    lambda g: g.pop("routes"),
    lambda g: g["places"][0].update(latitude=91),
    lambda g: g["places"][0].update(longitude=True),
    lambda g: g["places"][0].update(url="javascript:alert(1)"),
    lambda g: g["hotels"][0].update(photoURL="http://example.test/image.jpg"),
    lambda g: g["hotels"][0].update(quotedEnd="20270103"),
    lambda g: g.update(routes=[{"id": "walk", "name": "Walk", "section": "overview", "category": "walk", "approximate": True,
                               "source": "https://example.test/", "points": [[13, 100], [14, 200]]}]),
])
def test_invalid_guide_rejected_without_mutating_plan(client, change):
    m = model()
    g = guide()
    change(g)
    m["phases"][0]["guide"] = g
    before = s.snapshot()[1]
    r = client.post("/admin/api/travel/publish", auth=AUTH, headers=HEADERS, json={"revision": before, "files": files(m)})
    assert r.status_code == 422
    assert s.snapshot()[1] == before


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
