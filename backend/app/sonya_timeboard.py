"""Public restricted calendar with one editable note per date."""
from datetime import date, timedelta
import json
from collections import deque
from threading import Lock
import time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from app.timeboard import state, apply, Packet, EntryId, HEADERS, current_sonya_comments

router = APIRouter(prefix="/timeboard/sonya", include_in_schema=False)
STATIC = Path(__file__).parent / "static" / "sonya-timeboard"
START = date(2026, 11, 25)
END = date(2027, 2, 11)
_write_times = deque(maxlen=50)
_rate_lock = Lock()


def shared(entry):
    return (entry["cat"] == "with_sonya" or entry.get("shareWithSonya", False)) and not entry["title"].startswith(
        ("Через 7 дней · ", "Через 7 дней: ", "Завтра · "))


def public_projection(entries):
    relevant = [e for e in entries if e["cat"] == "sonya" or shared(e)]
    last = max([END] + [date.fromisoformat(e.get("endDate") or e["date"]) for e in relevant])
    last = min(last, START + timedelta(days=366))
    notes = current_sonya_comments(entries)
    days = []
    day = START
    while day <= last:
        key = day.isoformat()
        dated = [e for e in entries if e["cat"] == "sonya" and e["date"] == key]
        weekly = [e for e in entries if e["cat"] == "sonya" and e.get("sonyaRole") == "weekly"
                  and e["date"] <= key and date.fromisoformat(e["date"]).weekday() == day.weekday()]
        override = any(e.get("sonyaRole") == "override" for e in dated)
        schedule = ([] if override else weekly) + [e for e in dated if e.get("sonyaRole", "") not in ("weekly", "indicator", "comment")]
        phase = next((e["phase"] for e in dated if e.get("phase") and e.get("sonyaRole") != "indicator"), None)
        phase = phase or next((e["phase"] for e in dated if e.get("phase")), "")
        meetings = []
        for e in entries:
            if shared(e) and e["date"] <= key <= (e.get("endDate") or e["date"]):
                meetings.append({"time": e.get("time") if e["date"] == key and e.get("sonyaTimeConfirmed") else None,
                                 "comment": e.get("sonyaComment", "")})
        days.append({"date": key, "phase": phase,
            "schedule": [{k: e.get(k) for k in ("title", "time", "duration", "note")} for e in schedule],
            "meetings": meetings,
            "comments": [{"note": notes[key].get("note", ""), "createdAt": notes[key].get("createdAt"), "version": notes[key].get("updatedAt") or notes[key].get("createdAt")}] if key in notes else []})
        day += timedelta(days=1)
    return days


@router.get("")
def canonical():
    return RedirectResponse("/timeboard/sonya/", status_code=307, headers=HEADERS)


@router.get("/")
def page():
    return FileResponse(STATIC / "index.html", headers=HEADERS)


@router.get("/app.js")
def script():
    return FileResponse(STATIC / "app.js", headers=HEADERS)


@router.get("/style.css")
def stylesheet():
    return FileResponse(STATIC / "style.css", headers=HEADERS)


@router.get("/api/state")
def public_state():
    _, entries = state()
    return JSONResponse({"days": public_projection(entries)}, headers=HEADERS)


class Comment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: EntryId
    date: date
    note: str = Field(max_length=2000)
    expectedVersion: str | None = Field(default=None, max_length=80)


@router.post("/api/comments")
async def add_comment(request: Request):
    origin = request.headers.get("origin")
    if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.url.scheme, request.url.netloc):
        raise HTTPException(403, "Недопустимый источник")
    if request.headers.get("x-sonya-request") != "1" or request.headers.get("content-type", "").split(";",1)[0] != "application/json":
        raise HTTPException(403, "Используйте форму календаря")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>16000:
            raise HTTPException(413, "Слишком длинный комментарий")
    try:
        comment = Comment.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "Проверьте дату и комментарий") from None
    revision, entries = state()
    key = comment.date.isoformat()
    collision = next((e for e in entries if e['id']==comment.id),None)
    if collision and (collision['cat']!='sonya' or collision.get('sonyaRole')!='comment' or collision['date']!=key):
        raise HTTPException(409, "Повторите сохранение")
    if key not in {d['date'] for d in public_projection(entries)}:
        raise HTTPException(422, "Дата вне календаря")
    current = current_sonya_comments(entries).get(key)
    version = (current.get('updatedAt') or current.get('createdAt')) if current else None
    if (current.get('note','') if current else '')==comment.note:
        return JSONResponse({'ok':True,'note':comment.note,'version':version},headers=HEADERS)
    if version!=comment.expectedVersion:
        raise HTTPException(409, "Примечание изменилось. Обновите страницу перед редактированием.")
    with _rate_lock:
        tick = time.monotonic()
        while _write_times and tick-_write_times[0]>=86400:
            _write_times.popleft()
        if len(_write_times)>=50 or sum(tick-t<60 for t in _write_times)>=5:
            raise HTTPException(429,"Слишком часто. Попробуйте позже.")
        _write_times.append(tick)
    if current:
        op = {'op':'update','id':current['id'],'note':comment.note}
    else:
        op = {'op':'add','id':comment.id,'date':key,'cat':'sonya','title':'Комментарий Сони',
              'sonyaRole':'comment','note':comment.note}
    result = apply(Packet(v=1,baseRevision=revision,ops=[op]))
    after = json.loads(result.body)['changes'][0]['after']
    return JSONResponse({'ok':True,'note':after['note'],'version':after.get('updatedAt') or after.get('createdAt')},headers=HEADERS)
