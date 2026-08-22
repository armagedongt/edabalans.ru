from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, SessionLocal, engine, get_db
from app.engine import advance_run, due_runs, resume_callback, start_run
from app.models import BotInstance, Broadcast, BroadcastRecipient, Contact, ContentItem, ManualMessage, Sequence, SequenceRun, SequenceStep, SequenceVersion, StepDelivery, TrackingEvent, TrackingLink, UpdateReceipt
from app.schemas import AcceleratedRunIn, BroadcastIn, ContentUpdateIn, ManualMessageIn, StepUpdateIn, TrackingLinkIn
from app.seed import PREPURCHASE_CODE, seed_defaults
from app.telegram import TelegramClient


settings = get_settings()
security = HTTPBasic(auto_error=False)
STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
ADMIN_COOKIE = "edabalans_bot_admin"
ADMIN_SESSION_SECONDS = 60 * 60 * 24 * 7


def client() -> TelegramClient:
    if not settings.telegram_test_bot_token:
        raise HTTPException(503, "Telegram token is not configured")
    return TelegramClient(settings.telegram_test_bot_token, proxy_url=settings.telegram_proxy_url)


def _session_token(username: str, expires_at: int) -> str:
    payload = base64.urlsafe_b64encode(f"{username}|{expires_at}".encode()).decode().rstrip("=")
    signature = hmac.new(settings.admin_password.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _session_username(request: Request) -> str | None:
    token = request.cookies.get(ADMIN_COOKIE, "")
    try:
        payload, signature = token.rsplit(".", 1)
        expected = hmac.new(settings.admin_password.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(signature, expected):
            return None
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
        username, expires = decoded.rsplit("|", 1)
        if username != settings.admin_username or int(expires) < int(time.time()):
            return None
        return username
    except (ValueError, UnicodeDecodeError):
        return None


def _admin_identity(request: Request, credentials: HTTPBasicCredentials | None = None) -> str | None:
    if not settings.admin_username and not settings.admin_password:
        return "local-admin"
    cookie_username = _session_username(request)
    if cookie_username:
        return cookie_username
    valid = credentials and secrets.compare_digest(credentials.username, settings.admin_username) and secrets.compare_digest(credentials.password, settings.admin_password)
    return credentials.username if valid else None


def require_admin(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    identity = _admin_identity(request, credentials)
    if not identity:
        raise HTTPException(401, "Authentication required")
    return identity


def _bot(session: Session) -> BotInstance:
    bot = session.scalar(select(BotInstance).where(BotInstance.code == "test"))
    if not bot:
        raise HTTPException(503, "Bot is not initialized")
    return bot


def _upsert_contact(session: Session, bot: BotInstance, user: dict, chat: dict) -> Contact:
    telegram_id = str(user["id"])
    contact = session.scalar(select(Contact).where(Contact.bot_instance_id == bot.id, Contact.telegram_user_id == telegram_id))
    if not contact:
        contact = Contact(bot_instance_id=bot.id, telegram_user_id=telegram_id, chat_id=str(chat["id"]))
        session.add(contact)
    contact.chat_id = str(chat["id"])
    contact.username = user.get("username")
    contact.first_name = user.get("first_name")
    contact.last_name = user.get("last_name")
    contact.language_code = user.get("language_code")
    contact.last_seen_at = datetime.now(UTC)
    contact.status = "active"
    if not contact.user_id and session.bind and session.bind.dialect.name == "postgresql":
        crm_user_id = session.execute(text("SELECT user_id FROM messenger_accounts WHERE platform='telegram' AND platform_user_id=:telegram_id"), {"telegram_id": telegram_id}).scalar_one_or_none()
        if not crm_user_id:
            crm_user_id = session.execute(text("INSERT INTO users (display_name,status,data_origin,first_seen_at) VALUES (:name,'active','native',now()) RETURNING id"), {"name": " ".join(filter(None, [user.get('first_name'), user.get('last_name')])) or None}).scalar_one()
            session.execute(text("INSERT INTO messenger_accounts (user_id,platform,platform_user_id,username,first_name,first_seen_at,last_seen_at,linked_at,source) VALUES (:user_id,'telegram',:telegram_id,:username,:first_name,now(),now(),now(),'telegram_bot')"), {"user_id":crm_user_id,"telegram_id":telegram_id,"username":user.get("username"),"first_name":user.get("first_name")})
        else:
            session.execute(text("UPDATE messenger_accounts SET username=:username, first_name=:first_name, last_seen_at=now() WHERE platform='telegram' AND platform_user_id=:telegram_id"), {"telegram_id":telegram_id,"username":user.get("username"),"first_name":user.get("first_name")})
        contact.user_id = str(crm_user_id)
    session.flush()
    return contact


def _deliver_broadcast(session: Session, row: Broadcast, tg: TelegramClient) -> tuple[int, int]:
    contacts = session.scalars(select(Contact).where(Contact.status == row.segment.get("status", "active"))).all()
    existing = set(session.scalars(select(BroadcastRecipient.contact_id).where(BroadcastRecipient.broadcast_id == row.id)))
    for contact in contacts:
        if contact.id not in existing:
            session.add(BroadcastRecipient(broadcast_id=row.id, contact_id=contact.id))
    row.status = "sending"; row.started_at = row.started_at or datetime.now(UTC)
    content = session.get(ContentItem, row.content_item_id)
    sent = failed = 0
    session.flush()
    for recipient in session.scalars(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == row.id, BroadcastRecipient.status == "pending")):
        contact = session.get(Contact, recipient.contact_id)
        try:
            recipient.platform_message_id = tg.send_content(contact.chat_id, content, {})
            recipient.status = "sent"; recipient.sent_at = datetime.now(UTC); sent += 1
        except Exception as exc:
            message = str(exc)
            recipient.status = "failed"; recipient.error_message = message; failed += 1
            if "blocked by the user" in message.lower() or "chat not found" in message.lower():
                contact.status = "blocked"
    row.status = "completed" if not failed else "completed_with_errors"; row.finished_at = datetime.now(UTC)
    session.commit()
    return sent, failed


async def scheduler_loop() -> None:
    while True:
        try:
            with SessionLocal() as session:
                tg = TelegramClient(settings.telegram_test_bot_token, proxy_url=settings.telegram_proxy_url) if settings.telegram_test_bot_token else None
                if tg:
                    for run in due_runs(session):
                        advance_run(session, run, tg)
                    scheduled = session.scalars(select(Broadcast).where(Broadcast.status == "scheduled", Broadcast.scheduled_at <= datetime.now(UTC))).all()
                    for broadcast in scheduled:
                        _deliver_broadcast(session, broadcast, tg)
        except Exception:
            # A run keeps its own error. A scheduler-level failure is retried next tick.
            pass
        await asyncio.sleep(settings.scheduler_interval_seconds)


async def polling_loop() -> None:
    tg = TelegramClient(settings.telegram_test_bot_token, proxy_url=settings.telegram_proxy_url)
    offset: int | None = None
    webhook_removed = False
    while True:
        try:
            if not webhook_removed:
                await asyncio.to_thread(tg.delete_webhook)
                webhook_removed = True
            updates = await asyncio.to_thread(
                tg.get_updates,
                offset,
                settings.telegram_polling_timeout_seconds,
            )
            for update in updates:
                with SessionLocal() as session:
                    process_update(update, session)
                offset = int(update["update_id"]) + 1
        except asyncio.CancelledError:
            raise
        except Exception:
            # Network and Telegram outages are retried without acknowledging the update.
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_defaults(session, settings.telegram_test_bot_username)
    tasks = []
    if settings.scheduler_enabled:
        tasks.append(asyncio.create_task(scheduler_loop()))
    if settings.telegram_polling_enabled and settings.telegram_test_bot_token:
        tasks.append(asyncio.create_task(polling_loop()))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="edabalans Telegram service", version="0.1.0", lifespan=lifespan)


@app.get("/bot", include_in_schema=False)
def bot_admin(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)) -> FileResponse:
    page = "index.html" if _admin_identity(request, credentials) else "login.html"
    return FileResponse(STATIC_ROOT / page)


@app.get("/bot/{asset_name}", include_in_schema=False)
def bot_admin_asset(asset_name: str) -> FileResponse:
    if asset_name not in {"app.js", "login.js", "styles.css"}:
        raise HTTPException(404)
    return FileResponse(STATIC_ROOT / asset_name)


@app.post("/bot-api/login")
def bot_login(body: dict, response: Response) -> dict:
    username = str(body.get("username", "")).strip().lower()
    password = str(body.get("password", ""))
    valid = (
        settings.admin_username
        and settings.admin_password
        and secrets.compare_digest(username, settings.admin_username.lower())
        and secrets.compare_digest(password, settings.admin_password)
    )
    if not valid:
        raise HTTPException(401, "Неверная почта или пароль")
    expires_at = int(time.time()) + ADMIN_SESSION_SECONDS
    response.set_cookie(
        ADMIN_COOKIE,
        _session_token(settings.admin_username, expires_at),
        max_age=ADMIN_SESSION_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return {"ok": True}


@app.post("/bot-api/logout")
def bot_logout(response: Response) -> dict:
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return {"ok": True}


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "scheduler": settings.scheduler_enabled,
        "polling": settings.telegram_polling_enabled,
        "bot": settings.telegram_test_bot_username,
    }


@app.get("/r/{token}", include_in_schema=False)
def tracking_redirect(token: str, session: Session = Depends(get_db)) -> RedirectResponse:
    link = session.scalar(select(TrackingLink).where(TrackingLink.token == token, TrackingLink.is_active.is_(True)))
    if not link:
        raise HTTPException(404, "Tracking link not found")
    session.add(TrackingEvent(tracking_link_id=link.id, event_type="click", metadata_json={}))
    session.commit()
    username = settings.telegram_test_bot_username.lstrip("@")
    return RedirectResponse(f"https://t.me/{username}?start={token}", status_code=307)


def process_update(update: dict, session: Session) -> dict:
    bot = _bot(session)
    update_id = str(update.get("update_id", ""))
    if not update_id:
        raise HTTPException(400, "update_id is required")
    if session.get(UpdateReceipt, update_id):
        return {"ok": True, "duplicate": True}

    message = update.get("message")
    callback = update.get("callback_query")
    update_type = "callback_query" if callback else "message"
    session.add(UpdateReceipt(update_id=update_id, bot_instance_id=bot.id, update_type=update_type))

    if message:
        contact = _upsert_contact(session, bot, message["from"], message["chat"])
        text = message.get("text", "")
        if text.startswith("/start"):
            token = text.partition(" ")[2].strip() or None
            if token:
                link = session.scalar(select(TrackingLink).where(TrackingLink.token == token, TrackingLink.is_active.is_(True)))
                if link:
                    contact.first_source_token = contact.first_source_token or token
                    contact.last_source_token = token
                    session.add(TrackingEvent(tracking_link_id=link.id, contact_id=contact.id, event_type="start", metadata_json={}))
            run = start_run(session, contact.id, PREPURCHASE_CODE)
            session.commit()
            advance_run(session, run, client())
    elif callback:
        msg = callback.get("message") or {}
        contact = _upsert_contact(session, bot, callback["from"], msg.get("chat") or {"id": callback["from"]["id"]})
        run = resume_callback(session, contact.id, callback.get("data", ""))
        client().answer_callback(str(callback["id"]), "Интенсив запускается")
        if run:
            advance_run(session, run, client())
    session.commit()
    return {"ok": True}


@app.post("/telegram/webhook")
def telegram_webhook(update: dict, x_telegram_bot_api_secret_token: str | None = Header(default=None), session: Session = Depends(get_db)) -> dict:
    if settings.telegram_webhook_secret and not secrets.compare_digest(x_telegram_bot_api_secret_token or "", settings.telegram_webhook_secret):
        raise HTTPException(403, "Invalid webhook secret")
    return process_update(update, session)


@app.get("/bot-api/sequences", dependencies=[Depends(require_admin)])
def list_sequences(session: Session = Depends(get_db)) -> list[dict]:
    rows = session.execute(
        select(Sequence, SequenceVersion, func.count(SequenceStep.id))
        .join(SequenceVersion, SequenceVersion.sequence_id == Sequence.id)
        .outerjoin(SequenceStep, SequenceStep.sequence_version_id == SequenceVersion.id)
        .group_by(Sequence.id, SequenceVersion.id)
        .order_by(Sequence.name)
    ).all()
    return [{"code": seq.code, "name": seq.name, "status": seq.status, "version": ver.version_no, "version_status": ver.status, "steps": count} for seq, ver, count in rows]


@app.get("/bot-api/content", dependencies=[Depends(require_admin)])
def list_content(q: str = "", session: Session = Depends(get_db)) -> list[dict]:
    query = select(ContentItem).order_by(ContentItem.title)
    if q:
        query = query.where(ContentItem.title.ilike(f"%{q}%") | ContentItem.body_source.ilike(f"%{q}%"))
    return [{"id":i.id,"code":i.code,"title":i.title,"body_source":i.body_source,"media_kind":i.media_kind,"labels":i.labels,"origin_system":i.origin_system,"origin_scenario_name":i.origin_scenario_name} for i in session.scalars(query.limit(500))]


@app.get("/bot-api/sequences/{sequence_code}", dependencies=[Depends(require_admin)])
def sequence_detail(sequence_code: str, session: Session = Depends(get_db)) -> dict:
    seq = session.scalar(select(Sequence).where(Sequence.code == sequence_code))
    if not seq:
        raise HTTPException(404, "Sequence not found")
    version = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == seq.id).order_by(SequenceVersion.version_no.desc()))
    rows = session.execute(select(SequenceStep, ContentItem).outerjoin(ContentItem, ContentItem.id == SequenceStep.content_item_id).where(SequenceStep.sequence_version_id == version.id).order_by(SequenceStep.position)).all()
    return {"code":seq.code,"name":seq.name,"status":seq.status,"version":version.version_no,"steps":[{"id":step.id,"key":step.step_key,"position":step.position,"kind":step.kind,"label":step.label,"delay_seconds":step.delay_seconds,"enabled":step.enabled,"configuration":step.configuration,"content":{"id":content.id,"code":content.code,"title":content.title,"body_source":content.body_source,"media_kind":content.media_kind,"labels":content.labels} if content else None} for step,content in rows]}


@app.patch("/bot-api/content/{content_id}", dependencies=[Depends(require_admin)])
def update_content(content_id: str, body: ContentUpdateIn, session: Session = Depends(get_db)) -> dict:
    item = session.get(ContentItem, content_id)
    if not item:
        raise HTTPException(404, "Content not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    session.commit()
    return {"id":item.id,"title":item.title,"body_source":item.body_source,"labels":item.labels}


@app.patch("/bot-api/steps/{step_id}", dependencies=[Depends(require_admin)])
def update_step(step_id: str, body: StepUpdateIn, session: Session = Depends(get_db)) -> dict:
    step = session.get(SequenceStep, step_id)
    if not step:
        raise HTTPException(404, "Step not found")
    changes = body.model_dump(exclude_unset=True)
    if "position" in changes and changes["position"] != step.position:
        other = session.scalar(select(SequenceStep).where(SequenceStep.sequence_version_id == step.sequence_version_id, SequenceStep.position == changes["position"]))
        if other:
            old_position = step.position
            step.position = -1
            session.flush()
            other.position = old_position
            session.flush()
    for field, value in changes.items():
        setattr(step, field, value)
    session.commit()
    return {"id":step.id,"position":step.position,"delay_seconds":step.delay_seconds,"enabled":step.enabled,"configuration":step.configuration}


@app.get("/bot-api/contacts", dependencies=[Depends(require_admin)])
def list_contacts(session: Session = Depends(get_db)) -> list[dict]:
    contacts = session.scalars(select(Contact).order_by(Contact.last_seen_at.desc())).all()
    result = []
    for contact in contacts:
        run = session.scalar(select(SequenceRun).where(SequenceRun.contact_id == contact.id).order_by(SequenceRun.started_at.desc()))
        sent = session.scalar(select(func.count(StepDelivery.id)).where(StepDelivery.run_id == run.id, StepDelivery.status == "sent")) if run else 0
        result.append({"id":contact.id,"telegram_user_id":contact.telegram_user_id,"username":contact.username,"name":" ".join(filter(None,[contact.first_name,contact.last_name])),"status":contact.status,"run_status":run.status if run else None,"current_step":run.current_step_key if run else None,"next_action_at":run.next_action_at if run else None,"sent":sent,"time_scale":run.time_scale if run else None,"error":run.last_error if run else None})
    return result


def _user_bot_state(session: Session, user_id: str) -> dict | None:
    contact = session.scalar(select(Contact).where(Contact.user_id == user_id).order_by(Contact.last_seen_at.desc()))
    if not contact:
        return None
    run = session.scalar(select(SequenceRun).where(SequenceRun.contact_id == contact.id).order_by(SequenceRun.started_at.desc()))
    sent = total = 0
    if run:
        sent = session.scalar(select(func.count(StepDelivery.id)).where(StepDelivery.run_id == run.id, StepDelivery.status == "sent")) or 0
        total = session.scalar(select(func.count(SequenceStep.id)).where(SequenceStep.sequence_version_id == run.sequence_version_id, SequenceStep.kind.in_(["MESSAGE", "VIDEO_NOTE", "VIDEO", "VOICE", "PHOTO"]))) or 0
    return {"contact_id":contact.id,"telegram_user_id":contact.telegram_user_id,"username":contact.username,"contact_status":contact.status,"run_id":run.id if run else None,"run_status":run.status if run else None,"current_step":run.current_step_key if run else None,"next_action_at":run.next_action_at if run else None,"sent":sent,"total":total,"time_scale":run.time_scale if run else None,"error":run.last_error if run else None}


@app.get("/bot-api/users/{user_id}", dependencies=[Depends(require_admin)])
def user_bot_state(user_id: str, session: Session = Depends(get_db)) -> dict:
    state = _user_bot_state(session, user_id)
    if not state:
        raise HTTPException(404, "Telegram contact not found")
    return state


@app.post("/bot-api/contacts/{contact_id}/accelerated-run", dependencies=[Depends(require_admin)])
def accelerated_run(contact_id: str, body: AcceleratedRunIn, session: Session = Depends(get_db)) -> dict:
    if not session.get(Contact, contact_id):
        raise HTTPException(404, "Contact not found")
    runs = list(session.scalars(select(SequenceRun).where(SequenceRun.contact_id == contact_id)))
    if body.reset_technical_state and runs:
        session.execute(delete(StepDelivery).where(StepDelivery.run_id.in_([r.id for r in runs])))
        session.execute(delete(SequenceRun).where(SequenceRun.contact_id == contact_id))
    run = start_run(session, contact_id, body.sequence_code, body.time_scale)
    session.commit()
    advance_run(session, run, client())
    return {"run_id": run.id, "time_scale": run.time_scale, "status": run.status, "current_step": run.current_step_key}


@app.post("/bot-api/contacts/{contact_id}/messages", dependencies=[Depends(require_admin)])
def manual_message(contact_id: str, body: ManualMessageIn, admin: str = Depends(require_admin), session: Session = Depends(get_db)) -> dict:
    contact = session.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    log = ManualMessage(contact_id=contact.id, direction="out", body_source=body.text, status="pending", operator_email=admin)
    session.add(log); session.flush()
    content = SimpleNamespace(body_source=body.text, title="Ручное сообщение", media_kind=None, media_path=None, telegram_file_id=None)
    try:
        log.platform_message_id = client().send_content(contact.chat_id, content, {})
        log.status = "sent"
    except Exception as exc:
        log.status = "failed"; session.commit(); raise HTTPException(502, str(exc))
    session.commit()
    return {"id": log.id, "status": log.status, "platform_message_id": log.platform_message_id}


@app.post("/bot-api/users/{user_id}/messages", dependencies=[Depends(require_admin)])
def manual_message_by_user(user_id: str, body: ManualMessageIn, admin: str = Depends(require_admin), session: Session = Depends(get_db)) -> dict:
    contact = session.scalar(select(Contact).where(Contact.user_id == user_id).order_by(Contact.last_seen_at.desc()))
    if not contact:
        raise HTTPException(404, "Telegram contact not found")
    return manual_message(contact.id, body, admin, session)


@app.post("/bot-api/tracking-links", dependencies=[Depends(require_admin)])
def create_tracking_link(body: TrackingLinkIn, session: Session = Depends(get_db)) -> dict:
    token = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
    row = TrackingLink(token=token, platform=body.platform, placement=body.placement, campaign=body.campaign, target_sequence_code=body.target_sequence_code)
    session.add(row); session.commit()
    username = settings.telegram_test_bot_username.lstrip("@")
    base = settings.telegram_public_base_url.rstrip("/")
    return {"id": row.id, "token": token, "url": f"{base}/r/{token}" if base else f"https://t.me/{username}?start={token}", "deep_link": f"https://t.me/{username}?start={token}"}


@app.get("/bot-api/tracking-links", dependencies=[Depends(require_admin)])
def tracking_stats(session: Session = Depends(get_db)) -> list[dict]:
    rows = session.execute(select(TrackingLink, func.count(TrackingEvent.id)).outerjoin(TrackingEvent, TrackingEvent.tracking_link_id == TrackingLink.id).group_by(TrackingLink.id).order_by(TrackingLink.created_at.desc())).all()
    result = []
    for link, _ in rows:
        clicks = session.scalar(select(func.count(TrackingEvent.id)).where(TrackingEvent.tracking_link_id == link.id, TrackingEvent.event_type == "click")) or 0
        starts = session.scalar(select(func.count(TrackingEvent.id)).where(TrackingEvent.tracking_link_id == link.id, TrackingEvent.event_type == "start")) or 0
        result.append({"id":link.id,"token":link.token,"platform":link.platform,"placement":link.placement,"campaign":link.campaign,"clicks":clicks,"starts":starts})
    return result


@app.post("/bot-api/broadcasts", dependencies=[Depends(require_admin)])
def create_broadcast(body: BroadcastIn, admin: str = Depends(require_admin), session: Session = Depends(get_db)) -> dict:
    scheduled_at = datetime.fromisoformat(body.scheduled_at.replace("Z", "+00:00")) if body.scheduled_at else None
    if scheduled_at and scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    content = ContentItem(code=f"broadcast_{secrets.token_hex(6)}", title=body.title, body_source=body.text, labels=["разовая рассылка"], status="ready", origin_system="admin")
    session.add(content); session.flush()
    row = Broadcast(title=body.title, content_item_id=content.id, segment=body.segment, scheduled_at=scheduled_at, status="scheduled" if scheduled_at else "draft", created_by=admin)
    session.add(row); session.commit()
    return {"id":row.id,"status":row.status,"scheduled_at":row.scheduled_at}


@app.post("/bot-api/broadcasts/{broadcast_id}/launch", dependencies=[Depends(require_admin)])
def launch_broadcast(broadcast_id: str, session: Session = Depends(get_db)) -> dict:
    row = session.get(Broadcast, broadcast_id)
    if not row:
        raise HTTPException(404, "Broadcast not found")
    if row.status not in {"draft", "scheduled"}:
        raise HTTPException(409, "Broadcast already launched")
    sent, failed = _deliver_broadcast(session, row, client())
    return {"id":row.id,"status":row.status,"sent":sent,"failed":failed}


@app.get("/bot-api/broadcasts", dependencies=[Depends(require_admin)])
def list_broadcasts(session: Session = Depends(get_db)) -> list[dict]:
    rows = session.execute(select(Broadcast, func.count(BroadcastRecipient.id).filter(BroadcastRecipient.status == "sent"), func.count(BroadcastRecipient.id).filter(BroadcastRecipient.status == "failed")).outerjoin(BroadcastRecipient, BroadcastRecipient.broadcast_id == Broadcast.id).group_by(Broadcast.id).order_by(Broadcast.created_at.desc())).all()
    return [{"id":row.id,"title":row.title,"status":row.status,"scheduled_at":row.scheduled_at,"sent":sent,"failed":failed} for row,sent,failed in rows]
