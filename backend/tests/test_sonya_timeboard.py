import json
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite://")
from app.main import app
from app import timeboard, sonya_timeboard
from app.sonya_timeboard import public_projection


def entry(id="1", **values):
    return {"id": id.zfill(32), "date": "2026-12-04", "cat": "sonya", "title": "График", **values}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMEBOARD_DB", str(tmp_path / "board.sqlite3"))
    sonya_timeboard._write_times.clear()
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


def test_dated_override_and_note_do_not_rewrite_weekly_schedule():
    records = [entry(sonyaRole="weekly", date="2026-11-27", title="Работа"),
        entry("2", sonyaRole="override", title="Выходной"),
        entry("3", sonyaRole="comment", title="Комментарий Сони", note="Буду позже")]
    days = {d["date"]: d for d in public_projection(records)}
    assert [e["title"] for e in days["2026-12-04"]["schedule"]] == ["Выходной"]
    assert days["2026-12-04"]["comments"] == [{"note": "Буду позже", "createdAt": None, "version": None}]
    assert [e["title"] for e in days["2026-12-11"]["schedule"]] == ["Работа"]


def test_owner_reminders_are_not_shown_as_actual_meetings():
    records = [entry(cat="with_sonya", title="Через 7 дней · Поездка"),
        entry("2", cat="with_sonya", title="Завтра · Поездка"),
        entry("3", cat="with_sonya", title="Поездка", date="2026-12-11")]
    days = {d["date"]: d for d in public_projection(records)}
    assert days["2026-12-04"]["meetings"] == []
    assert len(days["2026-12-11"]["meetings"]) == 1


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


def test_anonymous_note_creation_is_idempotent_and_preserves_private_entries(client):
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
    {"note": "x" * 2001}, {"date": "2020-01-01"}, {"date": "invalid"}, {"id": "../data"}])
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


def test_public_write_rate_limit_counts_edits_not_only_new_rows(client):
    version = None
    for index in range(5):
        response = client.post('/timeboard/sonya/api/comments',json={'id':f'{index:032x}','date':'2026-12-04','note':f'Примечание {index}','expectedVersion':version},headers=HEADERS)
        assert response.status_code==200
        version=response.json()['version']
    assert len(timeboard.state()[1])==1
    assert client.post('/timeboard/sonya/api/comments',json={'id':'c'*32,'date':'2026-12-04','note':'Лишний','expectedVersion':version},headers=HEADERS).status_code==429


def test_note_edit_clear_retry_and_stale_version_preserve_one_record(client):
    payload={'id':'a'*32,'date':'2026-12-04','note':'Первое'}
    first=client.post('/timeboard/sonya/api/comments',json=payload,headers=HEADERS).json()
    revision,rows=timeboard.state(); identity=rows[0]['id']
    # Reading a note is separate from changing its contents.
    timeboard.apply(timeboard.Packet(v=1,baseRevision=revision,ops=[{'op':'update','id':identity,'done':True}]))
    updated={**payload,'id':'b'*32,'note':'Второе','expectedVersion':first['version']}
    response=client.post('/timeboard/sonya/api/comments',json=updated,headers=HEADERS)
    assert response.status_code==200 and response.json()['version']!=first['version']
    saved=timeboard.state();assert len(saved[1])==1 and saved[1][0]['id']==identity
    assert saved[1][0]['note']=='Второе' and not saved[1][0]['done']
    assert client.post('/timeboard/sonya/api/comments',json=updated,headers=HEADERS).status_code==200
    assert timeboard.state()==saved
    assert client.post('/timeboard/sonya/api/comments',json={**updated,'note':'Устаревший текст'},headers=HEADERS).status_code==409
    assert timeboard.state()==saved
    clear={**updated,'id':'c'*32,'note':'','expectedVersion':response.json()['version']}
    assert client.post('/timeboard/sonya/api/comments',json=clear,headers=HEADERS).status_code==200
    final=timeboard.state();assert len(final[1])==1 and final[1][0]['note']=='' and final[1][0]['id']==identity
    assert client.post('/timeboard/sonya/api/comments',json=clear,headers=HEADERS).status_code==200
    assert timeboard.state()==final


def test_legacy_multiple_comments_project_only_current_and_edit_that_one(client):
    timeboard.apply(timeboard.Packet(v=1,baseRevision=0,ops=[
      {'op':'add',**entry('a',sonyaRole='comment',note='Старое',createdAt='2026-11-25T10:00:00Z')},
      {'op':'add',**entry('b',sonyaRole='comment',note='Текущее',createdAt='2026-11-25T11:00:00Z')}]))
    day=next(d for d in client.get('/timeboard/sonya/api/state').json()['days'] if d['date']=='2026-12-04')
    assert len(day['comments'])==1 and day['comments'][0]['note']=='Текущее'
    response=client.post('/timeboard/sonya/api/comments',json={'id':'c'*32,'date':'2026-12-04','note':'Изменено','expectedVersion':day['comments'][0]['version']},headers=HEADERS)
    assert response.status_code==200
    rows=timeboard.state()[1];assert len(rows)==2 and rows[0]['note']=='Старое' and rows[1]['note']=='Изменено'
    assert timeboard.current_sonya_comments(rows)['2026-12-04']['id']=='b'.zfill(32)



def test_blank_new_note_does_not_create_record(client):
    before=timeboard.state()
    result=client.post('/timeboard/sonya/api/comments',json={'id':'d'*32,'date':'2026-12-04','note':'  ','expectedVersion':None},headers=HEADERS)
    assert result.status_code==200 and result.json()=={'ok':True,'note':'','version':None}
    assert timeboard.state()==before



def test_owner_note_edit_invalidates_public_version_but_mark_read_does_not(client):
    first=client.post('/timeboard/sonya/api/comments',json={'id':'a'*32,'date':'2026-12-04','note':'Первое'},headers=HEADERS).json()
    revision,rows=timeboard.state();identity=rows[0]['id']
    timeboard.apply(timeboard.Packet(v=1,baseRevision=revision,ops=[{'op':'update','id':identity,'note':'Правка владельца','done':True}]))
    saved=timeboard.state();assert saved[1][0]['updatedAt'] and not saved[1][0]['done']
    assert client.post('/timeboard/sonya/api/comments',json={'id':'b'*32,'date':'2026-12-04','note':'Устаревшая правка','expectedVersion':first['version']},headers=HEADERS).status_code==409
    assert timeboard.state()==saved
    version=saved[1][0]['updatedAt']
    timeboard.apply(timeboard.Packet(v=1,baseRevision=saved[0],ops=[{'op':'update','id':identity,'done':True}]))
    assert timeboard.state()[1][0]['updatedAt']==version


def test_public_saves_reach_real_notification_queue_once_per_edit(client):
    from datetime import UTC,datetime
    from sqlalchemy import select
    from app.models import MasterclassNotification
    from app.timeboard_notifications import enqueue_sonya_comments
    from test_admin_apps import make_client,add_user
    _,factory=make_client()
    with factory() as db:
        add_user(db,'armagedongt@gmail.com','Владелец');db.commit()
        version=None
        for text in ['Первое','Второе','']:
            response=client.post('/timeboard/sonya/api/comments',json={'id':'e'*32,'date':'2026-12-04','note':text,'expectedVersion':version},headers=HEADERS)
            assert response.status_code==200
            version=response.json()['version']
            assert enqueue_sonya_comments(db,datetime.now(UTC))==1
            assert enqueue_sonya_comments(db,datetime.now(UTC))==0
        rows=list(db.scalars(select(MasterclassNotification)))
        assert len(rows)==3 and len({r.deduplication_key for r in rows})==3
        assert all(r.payload['entry_ids']==['e'*32] for r in rows)
        assert any('Первое' in r.payload['message_text'] for r in rows)
        assert any('Второе' in r.payload['message_text'] for r in rows)
        assert any('Примечание очищено' in r.payload['message_text'] for r in rows)
        assert len(timeboard.state()[1])==1
