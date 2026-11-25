import json
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite://")
from app.main import app
from app import timeboard
from app.sonya_timeboard import public_projection


def entry(id="1", **values):
    return {"id": id.zfill(32), "date": "2026-12-04", "cat": "sonya", "title": "График", **values}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMEBOARD_DB", str(tmp_path / "board.sqlite3"))
    return TestClient(app)


def test_public_projection_exposes_only_schedule_and_explicit_meeting_fields():
    records = [entry(cat="finance", title="private finance", note="private card"),
        entry("2", cat="outside", title="private appointment"),
        entry("3", cat="with_sonya", title="private surprise", note="private location", url="https://private.test",
              time="19:00", sonyaComment="Надень удобную обувь", endDate="2026-12-05"),
        entry("4", sonyaRole="weekly", date="2026-11-27", title="Чкаловская", time="19:00", note="До 20:00"),
        entry("5", sonyaRole="indicator", phase="period")]
    days = {d["date"]: d for d in public_projection(records)}
    day = days["2026-12-04"]
    assert day["schedule"] == [{"title": "Чкаловская", "time": "19:00", "duration": None, "note": "До 20:00"}]
    assert day["phase"] == "period"
    assert day["meetings"] == [{"time": None, "comment": "Надень удобную обувь"}]
    assert days["2026-12-05"]["meetings"] == day["meetings"]
    serialized = json.dumps(days)
    assert "private" not in serialized and "url" not in serialized and '"id"' not in serialized
    records[2]["sonyaTimeConfirmed"] = True
    records[1]["shareWithSonya"] = True
    day = next(d for d in public_projection(records) if d["date"] == "2026-12-04")
    assert day["meetings"] == [{"time": None, "comment": ""}, {"time": "19:00", "comment": "Надень удобную обувь"}]


def test_dated_override_and_append_comment_do_not_rewrite_weekly_schedule():
    records = [entry(sonyaRole="weekly", date="2026-11-27", title="Работа"),
        entry("2", sonyaRole="override", title="Выходной"),
        entry("3", sonyaRole="comment", title="Комментарий Сони", note="Буду позже")]
    days = {d["date"]: d for d in public_projection(records)}
    assert [e["title"] for e in days["2026-12-04"]["schedule"]] == ["Выходной"]
    assert days["2026-12-04"]["comments"] == [{"note": "Буду позже", "createdAt": None}]
    assert [e["title"] for e in days["2026-12-11"]["schedule"]] == ["Работа"]


def test_public_page_and_resources_need_no_login_but_owner_data_stays_private(client):
    response = client.get("/timeboard/sonya", follow_redirects=False)
    assert response.status_code == 307 and response.headers["location"] == "/timeboard/sonya/"
    for path in ["", "app.js", "style.css", "api/state"]:
        response = client.get("/timeboard/sonya/" + path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
    assert client.get("/timeboard/api/state").status_code == 401
    assert client.get("/timeboard/sonya/.env").status_code == 404


HEADERS = {"X-Sonya-Request": "1"}


def test_anonymous_append_is_idempotent_and_cannot_edit_existing_entries(client):
    timeboard.apply(timeboard.Packet(v=1, baseRevision=0, ops=[
        {"op": "add", **entry("d", cat="finance", title="Приватный платёж", note="Карта" )},
        {"op": "add", **entry("e", sonyaRole="weekly", title="Рабочий график")}]))
    before = timeboard.state()
    payload = {"id": "a" * 32, "date": "2026-12-04", "note": "Изменения: начинаю в 16:00"}
    assert client.post("/timeboard/sonya/api/comments", json=payload, headers=HEADERS).status_code == 200
    revision, entries = timeboard.state()
    assert revision == before[0] + 1 and len(entries) == len(before[1]) + 1
    added = next(e for e in entries if e["id"] == payload["id"])
    assert added["cat"] == "sonya" and added["sonyaRole"] == "comment" and added["note"] == payload["note"]
    assert added["title"] == "Комментарий Сони" and added["createdAt"]
    assert entries[:-1] == before[1]
    assert client.post("/timeboard/sonya/api/comments", json=payload, headers=HEADERS).status_code == 200
    assert timeboard.state() == (revision, entries)
    assert client.post("/timeboard/sonya/api/comments", json={**payload, "id": before[1][0]["id"]}, headers=HEADERS).status_code == 409
    assert timeboard.state() == (revision, entries)
    assert client.post("/timeboard/sonya/api/comments", json={**payload, "note": "Переписать"}, headers=HEADERS).status_code == 409
    assert timeboard.state() == (revision, entries)
    day = next(d for d in client.get("/timeboard/sonya/api/state").json()["days"] if d["date"] == payload["date"])
    assert day["comments"][0]["note"] == payload["note"]


def test_owner_meeting_fields_persist_and_end_date_is_validated(client):
    added = entry(cat="outside", title="Личное название", shareWithSonya=True,
        sonyaComment="Возьми тёплые вещи", sonyaTimeConfirmed=True, time="12:30", endDate="2026-12-06")
    timeboard.apply(timeboard.Packet(v=1, baseRevision=0, ops=[{"op": "add", **added}]))
    revision, entries = timeboard.state()
    assert all(entries[0][k] == v for k, v in added.items())
    for end in ["2026-12-03", "2028-12-04"]:
        with pytest.raises(HTTPException) as error:
            timeboard.apply(timeboard.Packet(v=1, baseRevision=revision, ops=[{"op": "update", "id": added["id"], "endDate": end}]))
        assert error.value.status_code == 422
        assert timeboard.state() == (revision, entries)


@pytest.mark.parametrize("changes", [{"cat": "finance"}, {"title": "override"}, {"op": "remove"},
    {"note": " "}, {"note": "x" * 2001}, {"date": "2020-01-01"}, {"date": "invalid"}, {"id": "../data"}])
def test_public_write_rejects_extra_fields_and_invalid_values(client, changes):
    before = timeboard.state()
    response = client.post("/timeboard/sonya/api/comments", json={"id": "b" * 32, "date": "2026-12-04", "note": "Текст", **changes}, headers=HEADERS)
    assert response.status_code == 422
    assert timeboard.state() == before


def test_public_write_requires_same_origin_form_and_limits_body(client):
    payload = {"id": "b" * 32, "date": "2026-12-04", "note": "Текст"}
    assert client.post("/timeboard/sonya/api/comments", json=payload).status_code == 403
    assert client.post("/timeboard/sonya/api/comments", json=payload, headers={**HEADERS, "Origin": "https://hostile.test"}).status_code == 403
    assert client.post("/timeboard/sonya/api/comments", content="x" * 16001, headers={**HEADERS, "Content-Type": "application/json"}).status_code == 413


def test_public_write_rate_limit(client):
    for index in range(5):
        response = client.post("/timeboard/sonya/api/comments", json={"id": f"{index:032x}", "date": "2026-12-04", "note": "Комментарий"}, headers=HEADERS)
        assert response.status_code == 200
    assert client.post("/timeboard/sonya/api/comments", json={"id": "c" * 32, "date": "2026-12-04", "note": "Лишний"}, headers=HEADERS).status_code == 429
