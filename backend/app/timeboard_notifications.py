"""Scheduled, read-only board snapshots in the existing notification outbox."""
import asyncio
import logging
from datetime import UTC, datetime, timedelta, timezone
from html import escape
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.account_auth_routes import ACCOUNT_MANAGER_EMAIL
from app.database import SessionLocal
from app.models import MasterclassNotification, UserEmail
from app.timeboard import CATEGORIES, state, storage_path

KIND = "owner_planning_summary"
MSK = timezone(timedelta(hours=3))
log = logging.getLogger(__name__)


def current_slot(now):
    local = now.astimezone(MSK)
    # A restart may catch up within this slot, never send yesterday's summary.
    if local.hour not in (6, 20) or local.minute >= 30:
        return None
    return local.replace(minute=0, second=0, microsecond=0)


def day_entries(entries, day):
    key = day.isoformat()
    dated = [e for e in entries if e.get("date") == key and
             e.get("sonyaRole") not in ("weekly", "indicator")]
    overridden = any(e.get("cat") == "sonya" and e.get("sonyaRole") == "override" for e in dated)
    regular = [] if overridden else [e for e in entries if e.get("cat") == "sonya" and
        e.get("sonyaRole") == "weekly" and e["date"] <= key and
        datetime.fromisoformat(e["date"]).weekday() == day.weekday()]
    return sorted([e for e in dated + regular if not e.get("done") and e.get("cat") != "history"],
                  key=lambda e: (e.get("time") or "99:99", e["id"]))


def render_messages(entries, slot):
    day = slot.date() + timedelta(days=slot.hour == 20)
    selected = day_entries(entries, day)
    title = f"План на {'сегодня' if slot.hour == 6 else 'завтра'} · {day:%d.%m.%Y}"
    lines = [f"{title}\nВремя — МСК (UTC+3)."]
    if not selected:
        lines.append("Незавершённых дел на эту дату в доске нет.")
    for category, label in CATEGORIES.items():
        grouped = [entry for entry in selected if entry["cat"] == category]
        if not grouped:
            continue
        lines.extend(["", ("heading", label)])
        for number, entry in enumerate(grouped, 1):
            timing = f"{entry['time']} · " if entry.get("time") else ""
            lines.append(f"{number}. {timing}{entry['title']}" +
                         (f"\n{entry['note']}" if entry.get("note") else ""))
            if entry.get("url"):
                lines.append(("Открыть запись", entry["url"]))
    # Escape before packing. Small pieces bound Telegram's UTF-16 text length,
    # including hostile HTML and emoji; no note is silently truncated.
    parts, text = [], ""
    for line in lines:
        if isinstance(line, tuple) and line[0] == "heading":
            pieces = [f"<b>{escape(line[1], quote=False)}</b>"]
        elif isinstance(line, tuple):
            label, url = line
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None:
                continue
            pieces = [f'<a href="{escape(url, quote=True)}">{label}</a>']
        else:
            pieces = [escape(line[start:start + 400], quote=False) for start in range(0, len(line), 400)] or [""]
        for piece in pieces:
            if len((text + piece).encode("utf-16-le")) // 2 > 3300:
                parts.append(text.rstrip())
                text = ""
            text += piece + "\n"
    if text:
        parts.append(text.rstrip())
    board = '<a href="https://похудение-это-есть.рф/timeboard/">Открыть доску</a>'
    return [part + "\n\n" + board for part in parts], [e["id"] for e in selected], day


def enqueue_summary(db, now, snapshot=state):
    slot = current_slot(now)
    if slot is None:
        return 0
    owner = db.scalar(select(UserEmail.user_id).where(UserEmail.email_normalized == ACCOUNT_MANAGER_EMAIL))
    if owner is None:
        raise RuntimeError("planning owner account is not configured")
    prefix = f"timeboard:{slot.isoformat()}"
    if db.scalar(select(MasterclassNotification.id).where(
            MasterclassNotification.user_id == owner,
            MasterclassNotification.deduplication_key == f"{prefix}:1")):
        return 0
    revision, entries = snapshot()
    messages, ids, day = render_messages(entries, slot)
    for index, message in enumerate(messages, 1):
        db.add(MasterclassNotification(user_id=owner, notification_kind=KIND,
            deduplication_key=f"{prefix}:{index}", due_at=now + timedelta(milliseconds=index - 1),
            expires_at=slot.astimezone(UTC) + timedelta(minutes=30),
            payload={"delivery_role": "planning", "message_text": message,
                     "board_revision": revision, "entry_ids": ids, "target_date": day.isoformat(),
                     "scheduled_at": slot.isoformat(), "part": index, "parts": len(messages)}))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Another backend worker may have atomically enqueued this same slot.
        if not db.scalar(select(MasterclassNotification.id).where(
                MasterclassNotification.user_id == owner,
                MasterclassNotification.deduplication_key == f"{prefix}:1")):
            raise
        return 0
    return len(messages)


def enqueue_current_summary():
    if not storage_path().is_file():
        raise RuntimeError("timeboard storage is unavailable")
    with SessionLocal() as db:
        return enqueue_summary(db, datetime.now(UTC))


async def planning_worker(stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(enqueue_current_summary)
        except Exception:
            # Do not log private board contents, SQL parameters or secrets.
            log.error("Timeboard summary enqueue failed; retrying on the next tick")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
