import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, UTC
from datetime import date as CalendarDate
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from app.auth import admin_identity, security

HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Referrer-Policy": "no-referrer",
}

def require_timeboard_admin(request: Request, credentials=Depends(security)) -> str:
    identity = admin_identity(request, credentials)
    if not identity:
        raise HTTPException(401, "Требуется вход администратора", headers=HEADERS)
    return identity


router = APIRouter(prefix="/timeboard/api", include_in_schema=False,
                   dependencies=[Depends(require_timeboard_admin)])


CATEGORIES = {
    "outside": "Дела в городе",
    "with_sonya": "С Соней",
    "training": "Тренировки",
    "competitions": "Соревнования",
    "work": "Работа",
    "client_payments": "Оплаты клиентов",
    "posts": "Публикации",
    "finance": "Финансы",
    "history": "Дневник",
    "sonya": "Соня",
}
Category = Literal["outside", "with_sonya", "training", "competitions", "work", "client_payments", "posts", "finance", "history", "sonya"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Clock = Annotated[str, StringConstraints(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]
EntryId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
MAX_PACKET_BYTES = 800_000
MAX_ENTRIES = 2_000


class EntryFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: CalendarDate | None = None
    cat: Category | None = None
    title: Title | None = None
    time: Clock | None = None
    duration: int | None = Field(default=None, ge=1, le=1440, strict=True)
    note: str = Field(default="", max_length=2000)
    url: str = Field(default="", max_length=2000)
    flag: Literal["", "blue", "green", "red"] = ""
    phase: Literal["", "period", "ovulation"] = ""
    sonyaRole: Literal["", "weekly", "override", "indicator", "comment"] = ""
    done: bool = Field(default=False, strict=True)
    sonyaComment: str = Field(default="", max_length=2000)
    shareWithSonya: bool = Field(default=False, strict=True)
    sonyaTimeConfirmed: bool = Field(default=False, strict=True)
    endDate: CalendarDate | None = None
    createdAt: datetime | None = None
    updatedAt: datetime | None = None

    @field_validator("url")
    @classmethod
    def web_url(cls, value: str) -> str:
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username is not None:
                raise ValueError("Нужна ссылка http или https без учётных данных")
        return value


class Entry(EntryFields):
    id: str
    date: CalendarDate
    cat: Category
    title: Title


class Add(EntryFields):
    op: Literal["add"]
    id: EntryId | None = None
    date: CalendarDate
    cat: Category
    title: Title


class Update(EntryFields):
    op: Literal["update"]
    id: str = Field(min_length=1, max_length=64)


class Remove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["remove"]
    id: str = Field(min_length=1, max_length=64)


class Packet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1]
    baseRevision: int = Field(ge=0, strict=True)
    ops: list[Annotated[Add | Update | Remove, Field(discriminator="op")]] = Field(min_length=1, max_length=30)


def current_sonya_comments(entries):
    current = {}
    for entry in entries:
        if entry['cat']!='sonya' or entry.get('sonyaRole')!='comment':
            continue
        stamp = entry.get('updatedAt') or entry.get('createdAt')
        moment = datetime.fromisoformat(stamp) if stamp else datetime.min.replace(tzinfo=UTC)
        moment = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
        previous = current.get(entry['date'])
        if previous is None or moment>=previous[0]:
            current[entry['date']] = (moment,entry)
    return {key:item[1] for key,item in current.items()}


def storage_path() -> Path:
    return Path(os.environ.get("TIMEBOARD_DB", "/var/lib/timeboard/board.sqlite3"))


def read_state(db: sqlite3.Connection) -> tuple[int, list[dict]]:
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='board' AND type='table'").fetchone()
    if not exists:
        return 0, []
    row = db.execute("SELECT revision, entries FROM board WHERE id=1").fetchone()
    return (row[0], json.loads(row[1])) if row else (0, [])


def state() -> tuple[int, list[dict]]:
    path = storage_path()
    if not path.is_file():
        return 0, []
    with closing(sqlite3.connect(path, timeout=5)) as db:
        return read_state(db)


def public_response(data: dict) -> JSONResponse:
    return JSONResponse(data, headers=HEADERS)


@router.get("/state")
def get_state() -> JSONResponse:
    revision, entries = state()
    return public_response({"v": 1, "revision": revision, "timezone": "Europe/Moscow", "categories": CATEGORIES, "entries": entries})


@router.get("/session")
def get_session(request: Request, credentials=Depends(security)) -> JSONResponse:
    return public_response({"canEdit": bool(admin_identity(request, credentials))})


async def read_packet(request: Request) -> Packet:
    if request.headers.get("x-timeboard-request") != "1":
        raise HTTPException(403, "Требуется заголовок X-Timeboard-Request: 1")
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise HTTPException(415, "Пакет передаётся как JSON")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_PACKET_BYTES:
            raise HTTPException(413, "Пакет слишком большой")
        body.extend(chunk)
    try:
        return Packet.model_validate_json(body)
    except ValidationError as error:
        issue = error.errors(include_input=False, include_context=False)[0]
        location = ".".join(map(str, issue["loc"]))
        raise HTTPException(422, f"Проверьте формат пакета ({location or 'JSON'}).") from error


def prepare(packet: Packet, revision: int, entries: list[dict]) -> tuple[list[dict], list[dict]]:
    if packet.baseRevision != revision:
        raise HTTPException(409, "Доска изменилась. Прочитайте актуальное состояние и соберите пакет заново.")
    current = {entry["id"]: entry for entry in entries}
    changes = []
    seen = set()
    for index, op in enumerate(packet.ops, start=1):
        identity = (op.id or uuid4().hex) if isinstance(op, Add) else op.id
        before = current.get(identity)
        if identity in seen:
            raise HTTPException(422, f"Операция {index}: ID должен встречаться один раз.")
        if isinstance(op, Add) and before is not None:
            raise HTTPException(422, f"Операция {index}: ID новой записи уже существует.")
        if not isinstance(op, Add) and before is None:
            raise HTTPException(422, f"Операция {index}: ID записи не найден.")
        seen.add(identity)
        if isinstance(op, Remove):
            del current[identity]
            after = None
        else:
            fields = op.model_dump(exclude_unset=True, exclude={"op", "id"})
            try:
                entry = Entry.model_validate({**(before or {}), **fields, "id": identity})
            except ValidationError as error:
                raise HTTPException(422, f"Операция {index}: проверьте дату, категорию и название.") from error
            if entry.cat=='sonya' and entry.sonyaRole=='comment':
                if not before and entry.createdAt is None:
                    entry=entry.model_copy(update={'createdAt':datetime.now(UTC)})
                elif before and (before.get('cat')!='sonya' or before.get('sonyaRole')!='comment'
                      or before.get('note','')!=entry.note or before['date']!=entry.date.isoformat()):
                    entry=entry.model_copy(update={'updatedAt':datetime.now(UTC),'done':False})
            if entry.endDate and (entry.endDate < entry.date or (entry.endDate-entry.date).days > 366):
                raise HTTPException(422, "Дата окончания должна быть в пределах года после начала.")
            if (entry.phase or entry.sonyaRole) and entry.cat != "sonya":
                raise HTTPException(422, f"Операция {index}: phase и sonyaRole доступны только для категории sonya.")
            if entry.sonyaRole == "indicator" and not entry.phase:
                raise HTTPException(422, f"Операция {index}: индикатору нужна метка фазы.")
            after = entry.model_dump(mode="json")
            current[identity] = after
        changes.append({"op": op.op, "before": before, "after": after})
    if len(current) > MAX_ENTRIES:
        raise HTTPException(422, "В доске достигнут предел записей.")
    return list(current.values()), changes


@router.post("/preview", dependencies=[Depends(require_timeboard_admin)])
def preview(packet: Annotated[Packet, Depends(read_packet)]) -> JSONResponse:
    revision, entries = state()
    _, changes = prepare(packet, revision, entries)
    return public_response({"revision": revision, "changes": changes})


@router.post("/apply", dependencies=[Depends(require_timeboard_admin)])
def apply(packet: Annotated[Packet, Depends(read_packet)]) -> JSONResponse:
    with closing(sqlite3.connect(storage_path(), timeout=5)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        revision, entries = read_state(db)
        updated, changes = prepare(packet, revision, entries)
        db.execute(
            "CREATE TABLE IF NOT EXISTS board (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, entries TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO board VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, entries=excluded.entries",
            (revision + 1, json.dumps(updated, ensure_ascii=False)),
        )
    return public_response({"revision": revision + 1, "applied": len(changes), "changes": changes})
