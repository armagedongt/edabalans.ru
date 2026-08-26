from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import case, delete, func, or_, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.customer_lifecycle import reconcile_masterclass_presale_runs, stop_presale_runs_from_purchase_events
from app.database import Base, SessionLocal, engine, get_db
from app.engine import advance_run, due_runs, resume_callback, resume_wait_timeout, start_run
from app.graph import module_graph, module_overview_graph, sequence_graph
from app.maintenance import DEFAULT_MAINTENANCE_MESSAGE, MAINTENANCE_CONTENT_CODE, allowed_telegram_ids, maintenance_allows, record_maintenance_contact
from app.masterclass_dispatch import dispatch_due_masterclass_notifications
from app.models import BotInstance, BotRoute, Broadcast, BroadcastRecipient, Contact, ContentItem, CrmMessengerAccount, CrmTag, CrmUserTag, ManualMessage, Sequence, SequenceRun, SequenceStep, SequenceVersion, StepDelivery, TrackingEvent, TrackingLink, TrackingLinkAlias, TrackingLinkTag, UpdateReceipt, UtmTagRule
from app.masterclass_link import consume_masterclass_link
from app.schemas import AcceleratedRunIn, AliasCreateIn, AliasStatusIn, BroadcastConfirmIn, BroadcastIn, BroadcastScheduleIn, BroadcastTestIn, ContentUpdateIn, LinkRuleIn, LinkRuleUpdate, ManualMessageIn, StepPresentationIn, StepUpdateIn, TagCreateIn, TrackingLinkIn, UtmParseIn, UtmRuleIn
from app.seed import LEGACY_PREPURCHASE_CODE, PREPURCHASE_CODE, START_ENTRY_CODE, WELCOME_CODE, seed_defaults
from app.start_router import StartFacts, decision_from_facts, execute_start_decision, inspect_start
from app.telegram import TelegramClient
from app.tracking import active_link, assign_first_touch, create_tracking_session, ensure_crm_identity, exact_utm_matches, generate_alias_token, normalize_value, parse_utm_url, resolve_alias, resolve_pending_channel_touch, resolve_start_payload, tag_code, unresolved_utm_groups


settings = get_settings()
logger = logging.getLogger(__name__)
security = HTTPBasic(auto_error=False)
STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
ADMIN_COOKIE = "edabalans_admin"
ADMIN_SESSION_SECONDS = 60 * 60 * 24 * 7
MEDIA_TYPES = {
    "image/jpeg": ("photo", ".jpg"),
    "image/png": ("photo", ".png"),
    "image/webp": ("photo", ".webp"),
    "video/mp4": ("video", ".mp4"),
    "audio/mpeg": ("voice", ".mp3"),
    "audio/ogg": ("voice", ".ogg"),
}
def client() -> TelegramClient:
    if not settings.telegram_test_bot_token:
        raise HTTPException(503, "Telegram token is not configured")
    return TelegramClient(
        settings.telegram_test_bot_token,
        proxy_url=settings.telegram_proxy_url,
        channel_id=settings.telegram_channel_id,
    )


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
    session.flush()
    ensure_crm_identity(session, contact, user)
    return contact


def _maintenance_allows_contact(contact: Contact) -> bool:
    return maintenance_allows(
        settings.telegram_maintenance_mode,
        settings.telegram_maintenance_allowed_user_ids,
        contact.telegram_user_id,
    )


def _maintenance_notice(session: Session) -> ContentItem | SimpleNamespace:
    item = session.scalar(select(ContentItem).where(ContentItem.code == MAINTENANCE_CONTENT_CODE))
    if item:
        return item
    return SimpleNamespace(
        code=MAINTENANCE_CONTENT_CODE,
        title="Режим ремонта",
        body_source=DEFAULT_MAINTENANCE_MESSAGE,
        media_kind=None,
        media_path=None,
        telegram_file_id=None,
    )


def _handle_maintenance_contact(
    session: Session,
    contact: Contact,
    update_id: str,
    interaction_type: str,
    metadata: dict | None = None,
) -> None:
    record_maintenance_contact(session, contact, update_id, interaction_type, metadata)
    client().send_content(contact.chat_id, _maintenance_notice(session), {})


def _record_incoming_message(session: Session, contact: Contact, message: dict) -> None:
    text_value = (message.get("text") or message.get("caption") or "").strip()
    media_kind = next((kind for kind in ("photo", "video", "video_note", "voice", "audio", "document", "sticker") if message.get(kind)), None)
    body = text_value
    if media_kind:
        label = {
            "photo": "Фото",
            "video": "Видео",
            "video_note": "Видеокружок",
            "voice": "Голосовое",
            "audio": "Аудио",
            "document": "Файл",
            "sticker": "Стикер",
        }[media_kind]
        body = f"[{label}]" + (f" {text_value}" if text_value else "")
    if not body:
        body = "[Неподдерживаемый тип сообщения]"
    session.add(ManualMessage(
        contact_id=contact.id,
        direction="in",
        body_source=body,
        status="received",
        platform_message_id=str(message.get("message_id", "")) or None,
    ))


def _validate_media_reference(media_path: str | None) -> None:
    if not media_path or media_path.startswith(("https://", "http://")):
        return
    candidate = Path(media_path)
    if not candidate.is_absolute():
        if "/" not in media_path and "\\" not in media_path:
            return  # Telegram file_id
        raise HTTPException(422, "Локальное медиа должно быть загружено через админку")
    root = Path(settings.media_root).resolve()
    try:
        candidate.resolve().relative_to(root)
    except ValueError:
        raise HTTPException(422, "Локальное медиа находится вне разрешённого каталога") from None


def _broadcast_contacts(session: Session, row: Broadcast) -> list[Contact]:
    segment = row.segment or {}
    query = select(Contact).where(Contact.status == segment.get("status", "active"))
    telegram_ids = [str(value) for value in segment.get("telegram_user_ids", []) if str(value).strip()]
    if telegram_ids:
        query = query.where(Contact.telegram_user_id.in_(telegram_ids))
    for tag_id in dict.fromkeys(segment.get("tag_ids", [])):
        query = query.where(Contact.user_id.in_(select(CrmUserTag.user_id).where(CrmUserTag.tag_id == tag_id)))
    product_codes = list(dict.fromkeys(segment.get("product_codes", [])))
    if product_codes:
        query = query.where(text("""
            EXISTS (
                SELECT 1 FROM payments p
                JOIN products pr ON pr.id = p.product_id
                WHERE p.user_id = tg_contacts.user_id
                  AND p.payment_status = 'paid'
                  AND pr.code = ANY(:broadcast_product_codes)
            )
        """)).params(broadcast_product_codes=product_codes)
    access_codes = list(dict.fromkeys(segment.get("access_codes", [])))
    if access_codes:
        query = query.where(text("""
            EXISTS (
                SELECT 1 FROM user_accesses ua
                JOIN resources r ON r.id = ua.resource_id
                WHERE ua.user_id = tg_contacts.user_id
                  AND ua.revoked_at IS NULL
                  AND (ua.expires_at IS NULL OR ua.expires_at > now())
                  AND r.code = ANY(:broadcast_access_codes)
            )
        """)).params(broadcast_access_codes=access_codes)
    return [contact for contact in session.scalars(query.order_by(Contact.created_at)) if _maintenance_allows_contact(contact)]


def _snapshot_broadcast_recipients(session: Session, row: Broadcast) -> list[Contact]:
    contacts = _broadcast_contacts(session, row)
    existing = set(session.scalars(select(BroadcastRecipient.contact_id).where(BroadcastRecipient.broadcast_id == row.id)))
    for contact in contacts:
        if contact.id not in existing:
            session.add(BroadcastRecipient(broadcast_id=row.id, contact_id=contact.id))
    session.flush()
    return contacts


def _deliver_broadcast(session: Session, row: Broadcast, tg: TelegramClient, *, snapshot: bool = False) -> tuple[int, int]:
    if snapshot:
        _snapshot_broadcast_recipients(session, row)
    row.status = "sending"; row.started_at = row.started_at or datetime.now(UTC)
    content = session.get(ContentItem, row.content_item_id)
    configuration = {"buttons": (row.segment or {}).get("_buttons", [])}
    sent = failed = 0
    for recipient in session.scalars(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == row.id, BroadcastRecipient.status == "pending")):
        contact = session.get(Contact, recipient.contact_id)
        if not contact or not _maintenance_allows_contact(contact):
            recipient.status = "skipped_maintenance"
            continue
        try:
            recipient.platform_message_id = tg.send_content(contact.chat_id, content, configuration)
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
                tg = TelegramClient(
                    settings.telegram_test_bot_token,
                    proxy_url=settings.telegram_proxy_url,
                    channel_id=settings.telegram_channel_id,
                ) if settings.telegram_test_bot_token else None
                if tg:
                    stopped_presale = stop_presale_runs_from_purchase_events(session)
                    stopped_presale += reconcile_masterclass_presale_runs(session)
                    if stopped_presale:
                        session.commit()
                    for run in due_runs(session):
                        contact = session.get(Contact, run.contact_id)
                        if not contact or not _maintenance_allows_contact(contact):
                            continue
                        if run.status == "waiting":
                            resume_wait_timeout(session, run)
                        advance_run(session, run, tg)
                    scheduled = session.scalars(select(Broadcast).where(Broadcast.status == "scheduled", Broadcast.scheduled_at <= datetime.now(UTC))).all()
                    for broadcast in scheduled:
                        _deliver_broadcast(session, broadcast, tg)
                    if settings.postpurchase_dispatch_enabled:
                        dispatch_due_masterclass_notifications(
                            session,
                            tg,
                            settings.masterclass_offers_url,
                            course_url=settings.masterclass_course_url,
                            account_url=settings.masterclass_account_url,
                            test_only=settings.postpurchase_test_only,
                            allowed_telegram_ids=(
                                settings.telegram_maintenance_allowed_user_ids
                                if settings.telegram_maintenance_mode
                                else None
                            ),
                        )
                    else:
                        dispatch_due_masterclass_notifications(
                            session,
                            tg,
                            settings.masterclass_offers_url,
                            course_url=settings.masterclass_course_url,
                            account_url=settings.masterclass_account_url,
                            allowed_telegram_ids=(
                                settings.telegram_maintenance_allowed_user_ids
                                if settings.telegram_maintenance_mode
                                else None
                            ),
                            notification_kinds={"dqs_app_link"},
                        )
        except Exception:
            # A run keeps its own error. A scheduler-level failure is retried next tick.
            logger.exception("Telegram scheduler iteration failed")
        await asyncio.sleep(settings.scheduler_interval_seconds)


async def polling_loop() -> None:
    tg = TelegramClient(
        settings.telegram_test_bot_token,
        proxy_url=settings.telegram_proxy_url,
        channel_id=settings.telegram_channel_id,
    )
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
            logger.exception("Telegram polling iteration failed")
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_defaults(
            session,
            settings.telegram_test_bot_username,
            enable_subscription_checks=bool(settings.telegram_channel_id),
        )
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
    if asset_name not in {"app.js", "login.js", "styles.css", "module-map.css"}:
        raise HTTPException(404)
    headers = {"Cache-Control": "no-store"} if asset_name == "login.js" else None
    return FileResponse(STATIC_ROOT / asset_name, headers=headers)


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
        "maintenance": settings.telegram_maintenance_mode,
    }


def _go_response(token: str, request: Request, session: Session) -> Response:
    alias, suffix_warning = resolve_alias(session, token)
    link = active_link(session, alias)
    if not link or not alias:
        raise HTTPException(404, "Ссылка не найдена или отключена")
    query = {key: value for key, value in request.query_params.multi_items() if key.casefold().startswith("utm_")}
    start_payload = alias.token
    if query and link.target_kind == "bot_start":
        start_payload = create_tracking_session(session, link, alias, query)
    destination = alias.telegram_invite_url if link.target_kind == "channel_invite" else f"https://t.me/{settings.telegram_test_bot_username.lstrip('@')}?start={start_payload}"
    if not destination:
        raise HTTPException(409, "Для ссылки на канал ещё не создан Telegram invite URL")
    session.add(TrackingEvent(tracking_link_id=link.id, alias_id=alias.id, event_type="web_click", metadata_json={"raw_query": query, "warning": suffix_warning, "path_token": token}))
    session.commit()
    if suffix_warning:
        safe_destination = destination.replace("&", "&amp;").replace('"', "&quot;")
        return HTMLResponse(f"""<!doctype html><html lang=\"ru\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Открыть Telegram</title><style>body{{margin:0;background:#f4f6f2;font:17px system-ui;color:#18251c;display:grid;place-items:center;min-height:100vh}}main{{max-width:520px;margin:20px;padding:34px;background:white;border-radius:24px;box-shadow:0 18px 60px #20382722}}a{{display:block;text-align:center;margin-top:22px;padding:15px;border-radius:14px;background:#26734a;color:white;text-decoration:none;font-weight:700}}</style><main><h1>Перед переходом в Telegram</h1><p>Если Telegram у вас открывается только через VPN, включите его сейчас. Затем нажмите кнопку ниже.</p><a href=\"{safe_destination}\">Открыть Telegram</a></main></html>""")
    return RedirectResponse(destination, status_code=307)


@app.get("/go/{token}", include_in_schema=False)
def go_redirect(token: str, request: Request, session: Session = Depends(get_db)) -> Response:
    return _go_response(token, request, session)


@app.get("/r/{token}", include_in_schema=False)
def tracking_redirect(token: str, request: Request, session: Session = Depends(get_db)) -> Response:
    return _go_response(token, request, session)


def process_update(update: dict, session: Session) -> dict:
    bot = _bot(session)
    update_id = str(update.get("update_id", ""))
    if not update_id:
        raise HTTPException(400, "update_id is required")
    receipt_id = f"{bot.id}:{update_id}"
    if session.get(UpdateReceipt, receipt_id):
        return {"ok": True, "duplicate": True}

    message = update.get("message")
    callback = update.get("callback_query")
    member = update.get("chat_member")
    join_request = update.get("chat_join_request")
    update_type = "chat_member" if member else ("chat_join_request" if join_request else ("callback_query" if callback else "message"))
    session.add(UpdateReceipt(update_id=receipt_id, bot_instance_id=bot.id, update_type=update_type))

    if member or join_request:
        payload = member or join_request
        invite_url = ((payload.get("invite_link") or {}).get("invite_link") or "").strip()
        person = ((member or {}).get("new_chat_member") or {}).get("user") or (join_request or {}).get("from") or {}
        accepted = bool(join_request) or ((member or {}).get("new_chat_member") or {}).get("status") in {"member", "administrator", "creator"}
        alias = session.scalar(select(TrackingLinkAlias).where(TrackingLinkAlias.telegram_invite_url == invite_url)) if invite_url else None
        link = active_link(session, alias)
        if accepted and person.get("id") and link and alias:
            event_kind = "channel_join_request" if join_request else "channel_join"
            session.add(TrackingEvent(tracking_link_id=link.id, alias_id=alias.id, telegram_user_id=str(person["id"]), event_type=event_kind, deduplication_key=f"telegram:{update_id}:{event_kind}", metadata_json={"invite_url": invite_url}))
    elif message:
        contact = _upsert_contact(session, bot, message["from"], message["chat"])
        text = message.get("text", "")
        normalized_start = text.strip().casefold() in {"start", "старт"}
        is_start = normalized_start or text.startswith("/start")
        if not is_start:
            _record_incoming_message(session, contact, message)
            if not _maintenance_allows_contact(contact):
                _handle_maintenance_contact(session, contact, receipt_id, "message")
                session.commit()
                return {"ok": True, "maintenance": True}
        if normalized_start:
            text = "/start"
        if text.startswith("/start"):
            token = text.partition(" ")[2].strip() or None
            handled, reply = consume_masterclass_link(session, contact, message["from"], token or "")
            if handled:
                if not _maintenance_allows_contact(contact):
                    _handle_maintenance_contact(
                        session,
                        contact,
                        receipt_id,
                        "start",
                        {"masterclass_link": True, "has_masterclass": True},
                    )
                    session.commit()
                    return {"ok": True, "maintenance": True, "masterclass_link": True}
                session.commit()
                client().send_content(
                    contact.chat_id,
                    SimpleNamespace(
                        body_source=reply,
                        media_kind=None,
                        media_path=None,
                        telegram_file_id=None,
                    ),
                    {},
                )
                return {"ok": True, "masterclass_link": True}
            route = session.scalar(
                select(BotRoute)
                .where(
                    BotRoute.trigger_kind == "telegram_command",
                    BotRoute.trigger_value == "/start",
                    BotRoute.enabled.is_(True),
                )
                .order_by(BotRoute.priority)
            )
            sequence_code = route.target_sequence_code if route else WELCOME_CODE
            link, alias, session_tag_ids, raw_query, payload_status = resolve_start_payload(session, token)
            if not link:
                pending_link, pending_alias, pending_query = resolve_pending_channel_touch(session, contact.telegram_user_id)
                if pending_link:
                    link, alias, raw_query, payload_status = pending_link, pending_alias, pending_query, "known_channel_touch"
            account = session.scalar(select(CrmMessengerAccount).where(CrmMessengerAccount.platform == "telegram", CrmMessengerAccount.platform_user_id == contact.telegram_user_id))
            maintenance_allowed = _maintenance_allows_contact(contact)
            is_first, _ = assign_first_touch(
                session,
                account,
                contact,
                link,
                alias,
                session_tag_ids,
                raw_query,
                payload_status,
                mark_scenario_seen=maintenance_allowed,
            )
            if link and link.route_kind == "published_step":
                sequence_code = link.target_sequence_code
            facts, decision, welcome_run = inspect_start(session, contact, is_first)
            if not maintenance_allowed:
                _handle_maintenance_contact(
                    session,
                    contact,
                    receipt_id,
                    "start",
                    {
                        "has_masterclass": facts.has_masterclass,
                        "payload_status": payload_status,
                        "tracking_link_id": link.id if link else None,
                    },
                )
                session.commit()
                return {"ok": True, "maintenance": True}
            tg = client()
            run = execute_start_decision(
                session,
                contact,
                decision,
                welcome_run,
                tg,
                sequence_code,
                link.target_step_key if link and link.route_kind == "published_step" else None,
                update_id,
            )
            session.commit()
            if run:
                advance_run(session, run, tg)
    elif callback:
        msg = callback.get("message") or {}
        contact = _upsert_contact(session, bot, callback["from"], msg.get("chat") or {"id": callback["from"]["id"]})
        if not _maintenance_allows_contact(contact):
            client().answer_callback(str(callback["id"]), "Бот временно на ремонте")
            _handle_maintenance_contact(session, contact, receipt_id, "callback_query")
            session.commit()
            return {"ok": True, "maintenance": True}
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
    start_graph = module_graph(session, "start_attribution")
    result = [{
        "code": "start_attribution",
        "name": "1. Старт и атрибуция",
        "description": "Все входы, проверки, развилки и редактируемые ответы до передачи в Welcome.",
        "status": "published",
        "version": "system",
        "version_status": "current",
        "steps": len(start_graph["nodes"]),
        "item_type": "module",
    }]
    sequences = session.scalars(
        select(Sequence)
        .where(Sequence.code.not_in([START_ENTRY_CODE, LEGACY_PREPURCHASE_CODE]), Sequence.status != "archived")
        .order_by(Sequence.name)
    )
    for seq in sequences:
        ver = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == seq.id).order_by(SequenceVersion.version_no.desc()))
        if not ver:
            continue
        count = session.scalar(select(func.count(SequenceStep.id)).where(SequenceStep.sequence_version_id == ver.id)) or 0
        result.append({"code": seq.code, "name": seq.name, "description": seq.description, "status": seq.status, "version": ver.version_no, "version_status": ver.status, "steps": count, "item_type": "sequence"})
    return result


@app.get("/bot-api/map", dependencies=[Depends(require_admin)])
def bot_map(sequence_code: str | None = None, module_code: str | None = None, version_status: str = "published", session: Session = Depends(get_db)) -> dict:
    if version_status not in {"published", "draft", ""}:
        raise HTTPException(422, "version_status must be published or draft")
    if sequence_code and module_code:
        raise HTTPException(422, "Choose either sequence_code or module_code")
    try:
        if sequence_code:
            return sequence_graph(session, sequence_code, version_status)
        if module_code:
            return module_graph(session, module_code)
        return module_overview_graph(session)
    except LookupError:
        raise HTTPException(404, "Module or sequence not found") from None


@app.get("/bot-api/content", dependencies=[Depends(require_admin)])
def list_content(q: str = "", session: Session = Depends(get_db)) -> list[dict]:
    query = select(ContentItem).where(ContentItem.status != "archived").order_by(ContentItem.title)
    if q:
        query = query.where(ContentItem.title.ilike(f"%{q}%") | ContentItem.body_source.ilike(f"%{q}%"))
    return [{"id":i.id,"code":i.code,"title":i.title,"body_source":i.body_source,"media_kind":i.media_kind,"media_path":i.media_path,"labels":i.labels,"origin_system":i.origin_system,"origin_scenario_name":i.origin_scenario_name} for i in session.scalars(query.limit(2000))]


def _sequence_rule(code: str) -> dict:
    if code == WELCOME_CODE:
        return {
            "start": "Начинается для нового пользователя после завершения модуля Start и атрибуции.",
            "stop": "После Дня 4 ждёт 12 часов; покупка внутри Welcome не проверяется.",
            "next": "Передаёт в 25-дневную основную рассылку. Покупка останавливает presale централизованным lifecycle-событием.",
        }
    if code == PREPURCHASE_CODE:
        return {
            "start": "Запускается после завершения Welcome: 10 дней ежедневно, затем через день до дня 24.",
            "stop": "Останавливается сразу после появления подтверждённой покупки мастер-класса.",
            "next": "Без покупки завершается на 25-й день. После покупки связь продолжается через персональный M-link.",
        }
    if code == "postpurchase_masterclass":
        return {
            "start": "Запускается после подтверждения покупки мастер-класса.",
            "stop": "Завершается на 7-й день после первого открытия итогового саморевью.",
            "next": "Следующий postmasterclass-модуль создан пустым и отключён до отдельного утверждения.",
        }
    return {"start": "Запускается по настроенному событию.", "stop": "Завершается последним блоком.", "next": "Дальнейший переход не настроен."}


@app.get("/bot-api/sequences/{sequence_code}", dependencies=[Depends(require_admin)])
def sequence_detail(sequence_code: str, session: Session = Depends(get_db)) -> dict:
    seq = session.scalar(select(Sequence).where(Sequence.code == sequence_code))
    if not seq:
        raise HTTPException(404, "Sequence not found")
    version = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == seq.id).order_by(SequenceVersion.version_no.desc()))
    rows = session.execute(select(SequenceStep, ContentItem).outerjoin(ContentItem, ContentItem.id == SequenceStep.content_item_id).where(SequenceStep.sequence_version_id == version.id).order_by(SequenceStep.position)).all()
    return {"code":seq.code,"name":seq.name,"description":seq.description,"status":seq.status,"version":version.version_no,"rule":_sequence_rule(seq.code),"steps":[{"id":step.id,"key":step.step_key,"position":step.position,"kind":step.kind,"label":step.label,"delay_seconds":step.delay_seconds,"enabled":step.enabled,"configuration":step.configuration,"content":{"id":content.id,"code":content.code,"title":content.title,"body_source":content.body_source,"media_kind":content.media_kind,"media_path":content.media_path,"labels":content.labels} if content else None} for step,content in rows]}


@app.patch("/bot-api/content/{content_id}", dependencies=[Depends(require_admin)])
def update_content(content_id: str, body: ContentUpdateIn, session: Session = Depends(get_db)) -> dict:
    item = session.get(ContentItem, content_id)
    if not item:
        raise HTTPException(404, "Content not found")
    values = body.model_dump(exclude_unset=True)
    _validate_media_reference(values.get("media_path"))
    for field, value in values.items():
        setattr(item, field, value)
    session.commit()
    return {"id":item.id,"title":item.title,"body_source":item.body_source,"labels":item.labels,"media_kind":item.media_kind,"media_path":item.media_path}


@app.post("/bot-api/media", dependencies=[Depends(require_admin)])
async def upload_media(file: UploadFile = File(...)) -> dict:
    media = MEDIA_TYPES.get(file.content_type or "")
    if not media:
        raise HTTPException(415, "Поддерживаются JPG, PNG, WEBP, MP4, MP3 и OGG")
    data = await file.read(50 * 1024 * 1024 + 1)
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "Файл больше 50 МБ")
    media_kind, suffix = media
    media_root = Path(settings.media_root)
    media_root.mkdir(parents=True, exist_ok=True)
    destination = media_root / f"admin-{secrets.token_hex(12)}{suffix}"
    destination.write_bytes(data)
    return {"media_kind": media_kind, "media_path": str(destination), "filename": file.filename}


@app.patch("/bot-api/steps/{step_id}", dependencies=[Depends(require_admin)])
def update_step(step_id: str, body: StepUpdateIn, session: Session = Depends(get_db)) -> dict:
    step = session.get(SequenceStep, step_id)
    if not step:
        raise HTTPException(404, "Step not found")
    raise HTTPException(409, "Логика графа доступна только для чтения; изменяйте тексты и медиа контентных блоков")


@app.patch("/bot-api/steps/{step_id}/presentation", dependencies=[Depends(require_admin)])
def update_step_presentation(step_id: str, body: StepPresentationIn, session: Session = Depends(get_db)) -> dict:
    """Edit button wording while keeping callback, URL and graph routing immutable."""
    step = session.get(SequenceStep, step_id)
    if not step:
        raise HTTPException(404, "Step not found")
    configuration = dict(step.configuration or {})
    buttons = [dict(button) for button in configuration.get("buttons", [])]
    if not buttons:
        raise HTTPException(409, "У этого сообщения нет редактируемой кнопки")
    buttons[0]["text"] = body.button_text
    configuration["buttons"] = buttons
    step.configuration = configuration
    session.commit()
    return {"id": step.id, "button_text": buttons[0]["text"], "configuration": configuration}


@app.get("/bot-api/contacts", dependencies=[Depends(require_admin)])
def list_contacts(session: Session = Depends(get_db)) -> list[dict]:
    contacts = session.scalars(select(Contact).order_by(Contact.last_seen_at.desc())).all()
    result = []
    for contact in contacts:
        run = session.scalar(select(SequenceRun).where(SequenceRun.contact_id == contact.id).order_by(case((SequenceRun.status.in_(["active", "waiting"]), 0), else_=1), SequenceRun.started_at.desc()))
        sent = session.scalar(select(func.count(StepDelivery.id)).where(StepDelivery.run_id == run.id, StepDelivery.status == "sent")) if run else 0
        total = session.scalar(select(func.count(SequenceStep.id)).where(SequenceStep.sequence_version_id == run.sequence_version_id, SequenceStep.kind.in_(["MESSAGE", "VIDEO_NOTE", "VIDEO", "VOICE", "PHOTO"]))) if run else 0
        result.append({"id":contact.id,"telegram_user_id":contact.telegram_user_id,"username":contact.username,"name":" ".join(filter(None,[contact.first_name,contact.last_name])),"status":contact.status,"run_status":run.status if run else None,"current_step":run.current_step_key if run else None,"next_action_at":run.next_action_at if run else None,"sent":sent,"total":total,"time_scale":run.time_scale if run else None,"error":run.last_error if run else None,"last_seen_at":contact.last_seen_at,"created_at":contact.created_at})
    return result


@app.get("/bot-api/contacts/{contact_id}/timeline", dependencies=[Depends(require_admin)])
def contact_timeline(contact_id: str, session: Session = Depends(get_db)) -> list[dict]:
    contact = session.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    events: list[dict] = []
    for message in session.scalars(
        select(ManualMessage)
        .where(ManualMessage.contact_id == contact_id)
        .order_by(ManualMessage.created_at.desc())
        .limit(200)
    ):
        events.append({
            "id": message.id,
            "kind": "manual",
            "direction": "incoming" if message.direction in {"in", "incoming"} else "outgoing",
            "body": message.body_source,
            "status": message.status,
            "occurred_at": message.created_at,
            "platform_message_id": message.platform_message_id,
        })
    automated = session.execute(
        select(StepDelivery, ContentItem)
        .join(SequenceRun, SequenceRun.id == StepDelivery.run_id)
        .outerjoin(
            SequenceStep,
            (SequenceStep.sequence_version_id == SequenceRun.sequence_version_id)
            & (SequenceStep.step_key == StepDelivery.step_key),
        )
        .outerjoin(ContentItem, ContentItem.id == SequenceStep.content_item_id)
        .where(SequenceRun.contact_id == contact_id, StepDelivery.status.in_(["sent", "failed"]))
        .order_by(StepDelivery.created_at.desc())
        .limit(200)
    ).all()
    for delivery, content in automated:
        events.append({
            "id": delivery.id,
            "kind": "sequence",
            "direction": "outgoing",
            "body": content.body_source if content else f"[{delivery.step_key}]",
            "status": delivery.status,
            "occurred_at": delivery.sent_at or delivery.created_at,
            "platform_message_id": delivery.platform_message_id,
        })
    broadcast_rows = session.execute(
        select(BroadcastRecipient, Broadcast, ContentItem)
        .join(Broadcast, Broadcast.id == BroadcastRecipient.broadcast_id)
        .join(ContentItem, ContentItem.id == Broadcast.content_item_id)
        .where(BroadcastRecipient.contact_id == contact_id)
        .order_by(BroadcastRecipient.sent_at.desc())
        .limit(200)
    ).all()
    for recipient, broadcast, content in broadcast_rows:
        events.append({
            "id": recipient.id,
            "kind": "broadcast",
            "direction": "outgoing",
            "body": content.body_source,
            "title": broadcast.title,
            "status": recipient.status,
            "occurred_at": recipient.sent_at or broadcast.started_at or broadcast.created_at,
            "platform_message_id": recipient.platform_message_id,
        })
    return sorted(events, key=lambda event: event["occurred_at"].isoformat() if event["occurred_at"] else "")[-200:]


def _user_bot_state(session: Session, user_id: str) -> dict | None:
    contact = session.scalar(select(Contact).where(Contact.user_id == user_id).order_by(Contact.last_seen_at.desc()))
    if not contact:
        return None
    run = session.scalar(select(SequenceRun).where(SequenceRun.contact_id == contact.id).order_by(case((SequenceRun.status.in_(["active", "waiting"]), 0), else_=1), SequenceRun.started_at.desc()))
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


@app.get("/bot-api/contacts/{contact_id}/start-preview", dependencies=[Depends(require_admin)])
def start_preview(contact_id: str, session: Session = Depends(get_db)) -> dict:
    contact = session.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    facts, decision, run = inspect_start(session, contact, False)
    return {"contact_id": contact.id, "facts": facts.__dict__, "decision": decision.to_dict(), "next_action_at": run.next_action_at if run else None}


@app.post("/bot-api/start-router/simulate", dependencies=[Depends(require_admin)])
def simulate_start_router(body: dict) -> dict:
    try:
        facts = StartFacts(**{key: bool(body[key]) for key in StartFacts.__dataclass_fields__})
    except KeyError as exc:
        raise HTTPException(422, f"Missing fact: {exc.args[0]}") from None
    return {"facts": facts.__dict__, "decision": decision_from_facts(facts).to_dict()}


@app.post("/bot-api/contacts/{contact_id}/accelerated-run", dependencies=[Depends(require_admin)])
def accelerated_run(contact_id: str, body: AcceleratedRunIn, session: Session = Depends(get_db)) -> dict:
    contact = session.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    if not _maintenance_allows_contact(contact):
        raise HTTPException(409, "Пользователь находится в листе ожидания режима ремонта")
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
    if not _maintenance_allows_contact(contact):
        raise HTTPException(409, "Во время ремонта сообщения разрешены только тестовым аккаунтам")
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
def create_tracking_link(body: TrackingLinkIn, admin: str = Depends(require_admin), session: Session = Depends(get_db)) -> dict:
    modern = LinkRuleIn(name=f"{body.platform} · {body.placement}", target_sequence_code=body.target_sequence_code)
    row = _create_link_rule(session, modern, admin, platform=body.platform, placement=body.placement, campaign=body.campaign)
    session.commit()
    return _link_payload(session, row)


def _create_link_rule(session: Session, body: LinkRuleIn, admin: str, platform: str = "", placement: str = "", campaign: str | None = None) -> TrackingLink:
    _validate_link_route(session, body.route_kind, body.target_sequence_code, body.target_step_key)
    alias_token = generate_alias_token(session, body.target_kind)
    row = TrackingLink(token=alias_token, name=body.name, platform=platform or "Не указана", placement=placement or body.name, campaign=campaign, target_kind=body.target_kind, route_kind=body.route_kind, target_sequence_code=body.target_sequence_code, target_step_key=body.target_step_key, created_by=admin)
    session.add(row); session.flush()
    for tag_id in dict.fromkeys(body.tag_ids):
        if not session.get(CrmTag, tag_id):
            raise HTTPException(422, f"Тег {tag_id} не найден")
        session.add(TrackingLinkTag(tracking_link_id=row.id, tag_id=tag_id))
    if body.create_alias:
        session.add(TrackingLinkAlias(tracking_link_id=row.id, token=alias_token, alias_kind="short", created_by=admin))
    return row


def _validate_link_route(session: Session, route_kind: str, sequence_code: str, step_key: str | None) -> None:
    if route_kind == "root":
        return
    if not step_key:
        raise HTTPException(422, "Для исключения укажите опубликованный шаг")
    exists = session.scalar(
        select(SequenceStep.id)
        .join(SequenceVersion, SequenceVersion.id == SequenceStep.sequence_version_id)
        .join(Sequence, Sequence.id == SequenceVersion.sequence_id)
        .where(Sequence.code == sequence_code, SequenceVersion.status == "published", SequenceStep.step_key == step_key, SequenceStep.enabled.is_(True))
    )
    if not exists:
        raise HTTPException(422, "Указанный шаг не найден в опубликованной версии цепочки")


def _link_payload(session: Session, link: TrackingLink) -> dict:
    aliases = list(session.scalars(select(TrackingLinkAlias).where(TrackingLinkAlias.tracking_link_id == link.id).order_by(TrackingLinkAlias.created_at)))
    tag_rows = session.execute(select(CrmTag.id, CrmTag.name).join(TrackingLinkTag, TrackingLinkTag.tag_id == CrmTag.id).where(TrackingLinkTag.tracking_link_id == link.id)).all()
    clicks = session.scalar(select(func.count(TrackingEvent.id)).where(TrackingEvent.tracking_link_id == link.id, TrackingEvent.event_type.in_(["click", "web_click"]))) or 0
    start_filter = or_(TrackingEvent.event_type == "start", TrackingEvent.event_type.like("start_%"))
    starts = session.scalar(select(func.count(TrackingEvent.id)).where(TrackingEvent.tracking_link_id == link.id, start_filter)) or 0
    unique_starts = session.scalar(select(func.count(func.distinct(TrackingEvent.user_id))).where(TrackingEvent.tracking_link_id == link.id, start_filter, TrackingEvent.user_id.is_not(None))) or 0
    username = settings.telegram_test_bot_username.lstrip("@")
    go_base = settings.telegram_public_base_url.rstrip("/")
    alias_data = []
    for alias in aliases:
        direct = alias.telegram_invite_url if link.target_kind == "channel_invite" else f"https://t.me/{username}?start={alias.token}"
        alias_clicks = session.scalar(select(func.count(TrackingEvent.id)).where(TrackingEvent.alias_id == alias.id, TrackingEvent.event_type.in_(["click", "web_click"]))) or 0
        alias_starts = session.scalar(select(func.count(TrackingEvent.id)).where(TrackingEvent.alias_id == alias.id, or_(TrackingEvent.event_type == "start", TrackingEvent.event_type.like("start_%")))) or 0
        alias_data.append({"id": alias.id, "token": alias.token, "kind": alias.alias_kind, "status": alias.status, "direct_url": direct, "go_url": f"{go_base}/{alias.token}" if go_base else None, "warning_url": f"{go_base}/{alias.token}V" if go_base and alias.alias_kind == "short" else None, "clicks": alias_clicks, "starts": alias_starts})
    return {"id": link.id, "name": link.name, "token": link.token, "platform": link.platform, "placement": link.placement, "campaign": link.campaign, "target_kind": link.target_kind, "route_kind": link.route_kind, "target_sequence_code": link.target_sequence_code, "target_step_key": link.target_step_key, "status": link.status, "is_active": link.is_active, "created_at": link.created_at, "tags": [{"id": tag_id, "name": name} for tag_id, name in tag_rows], "aliases": alias_data, "clicks": clicks, "starts": starts, "unique_starts": unique_starts, "conversion": round(unique_starts / clicks * 100, 1) if clicks else 0, "url": alias_data[0]["go_url"] if alias_data and alias_data[0]["go_url"] else (alias_data[0]["direct_url"] if alias_data else None), "deep_link": alias_data[0]["direct_url"] if alias_data else None}


@app.post("/bot-api/link-rules", dependencies=[Depends(require_admin)])
def create_link_rule(body: LinkRuleIn, admin: str = Depends(require_admin), session: Session = Depends(get_db)) -> dict:
    row = _create_link_rule(session, body, admin)
    session.commit()
    return _link_payload(session, row)


@app.get("/bot-api/link-rules", dependencies=[Depends(require_admin)])
def list_link_rules(session: Session = Depends(get_db)) -> list[dict]:
    return [_link_payload(session, row) for row in session.scalars(select(TrackingLink).order_by(TrackingLink.created_at.desc()))]


@app.post("/bot-api/link-rules/resolve-preview", dependencies=[Depends(require_admin)])
def resolve_link_preview(body: dict, session: Session = Depends(get_db)) -> dict:
    token = str(body.get("token", "")).strip()
    link, alias, tag_ids, raw_query, status = resolve_start_payload(session, token)
    if link:
        tag_ids = list(dict.fromkeys([*list(session.scalars(select(TrackingLinkTag.tag_id).where(TrackingLinkTag.tracking_link_id == link.id))), *tag_ids]))
    tags = list(session.scalars(select(CrmTag).where(CrmTag.id.in_(tag_ids)))) if tag_ids else []
    return {"payload": token, "status": status, "route": {"kind": link.route_kind, "sequence_code": link.target_sequence_code, "step_key": link.target_step_key} if link else {"kind": "root", "sequence_code": WELCOME_CODE, "step_key": None}, "rule": _link_payload(session, link) if link else None, "alias_id": alias.id if alias else None, "tags": [{"id": tag.id, "name": tag.name} for tag in tags], "raw_query": raw_query}


@app.get("/bot-api/link-rules/{link_id}", dependencies=[Depends(require_admin)])
def get_link_rule(link_id: str, session: Session = Depends(get_db)) -> dict:
    row = session.get(TrackingLink, link_id)
    if not row:
        raise HTTPException(404, "Правило не найдено")
    return _link_payload(session, row)


@app.patch("/bot-api/link-rules/{link_id}", dependencies=[Depends(require_admin)])
def update_link_rule(link_id: str, body: LinkRuleUpdate, session: Session = Depends(get_db)) -> dict:
    row = session.get(TrackingLink, link_id)
    if not row:
        raise HTTPException(404, "Правило не найдено")
    new_route = body.route_kind or row.route_kind
    new_sequence = body.target_sequence_code or row.target_sequence_code
    new_step = body.target_step_key if body.target_step_key is not None else row.target_step_key
    _validate_link_route(session, new_route, new_sequence, new_step)
    for key in ("name", "status", "route_kind", "target_sequence_code", "target_step_key"):
        value = getattr(body, key)
        if value is not None:
            setattr(row, key, value)
    if body.status is not None:
        row.is_active = body.status == "active"
        row.archived_at = datetime.now(UTC) if body.status == "archived" else None
    if body.tag_ids is not None:
        session.execute(delete(TrackingLinkTag).where(TrackingLinkTag.tracking_link_id == row.id))
        for tag_id in dict.fromkeys(body.tag_ids):
            if not session.get(CrmTag, tag_id):
                raise HTTPException(422, f"Тег {tag_id} не найден")
            session.add(TrackingLinkTag(tracking_link_id=row.id, tag_id=tag_id))
    session.commit()
    return _link_payload(session, row)


@app.post("/bot-api/link-rules/{link_id}/aliases", dependencies=[Depends(require_admin)])
def add_link_alias(link_id: str, body: AliasCreateIn, admin: str = Depends(require_admin), session: Session = Depends(get_db)) -> dict:
    link = session.get(TrackingLink, link_id)
    if not link:
        raise HTTPException(404, "Правило не найдено")
    token = body.token.strip() if body.token else generate_alias_token(session, link.target_kind)
    if session.scalar(select(TrackingLinkAlias.id).where(TrackingLinkAlias.token == token)):
        raise HTTPException(409, "Такой публичный код уже используется")
    alias = TrackingLinkAlias(tracking_link_id=link.id, token=token, alias_kind=body.alias_kind, created_by=admin)
    session.add(alias); session.commit()
    return _link_payload(session, link)


@app.patch("/bot-api/link-aliases/{alias_id}", dependencies=[Depends(require_admin)])
def set_link_alias_status(alias_id: str, body: AliasStatusIn, session: Session = Depends(get_db)) -> dict:
    alias = session.get(TrackingLinkAlias, alias_id)
    if not alias:
        raise HTTPException(404, "Код не найден")
    alias.status = body.status
    alias.archived_at = datetime.now(UTC) if body.status == "archived" else None
    session.commit()
    return {"id": alias.id, "status": alias.status}


@app.post("/bot-api/link-aliases/{alias_id}/channel-invite", dependencies=[Depends(require_admin)])
def create_channel_invite(alias_id: str, session: Session = Depends(get_db)) -> dict:
    alias = session.get(TrackingLinkAlias, alias_id)
    link = session.get(TrackingLink, alias.tracking_link_id) if alias else None
    if not alias or not link or link.target_kind != "channel_invite":
        raise HTTPException(404, "Код ссылки на канал не найден")
    if not settings.telegram_channel_id:
        raise HTTPException(409, "TELEGRAM_CHANNEL_ID ещё не настроен")
    if alias.telegram_invite_url:
        return {"id": alias.id, "invite_url": alias.telegram_invite_url, "already_created": True}
    result = client().create_chat_invite_link(settings.telegram_channel_id, f"{alias.token} · {link.name}", alias.creates_join_request)
    alias.telegram_invite_url = result["invite_link"]
    alias.telegram_chat_id = settings.telegram_channel_id
    session.commit()
    return {"id": alias.id, "invite_url": alias.telegram_invite_url, "already_created": False}


@app.post("/bot-api/link-aliases/{alias_id}/revoke-channel-invite", dependencies=[Depends(require_admin)])
def revoke_channel_invite(alias_id: str, session: Session = Depends(get_db)) -> dict:
    alias = session.get(TrackingLinkAlias, alias_id)
    if not alias or not alias.telegram_invite_url or not alias.telegram_chat_id:
        raise HTTPException(404, "Активная invite-ссылка не найдена")
    client().revoke_chat_invite_link(alias.telegram_chat_id, alias.telegram_invite_url)
    alias.status = "archived"; alias.archived_at = datetime.now(UTC)
    session.commit()
    return {"id": alias.id, "status": alias.status}


@app.get("/bot-api/tracking-links", dependencies=[Depends(require_admin)])
def tracking_stats(session: Session = Depends(get_db)) -> list[dict]:
    return list_link_rules(session)


@app.get("/bot-api/tracking-events", dependencies=[Depends(require_admin)])
def tracking_events(link_id: str | None = None, event_type: str | None = None, session: Session = Depends(get_db)) -> list[dict]:
    query = select(TrackingEvent).order_by(TrackingEvent.occurred_at.desc()).limit(1000)
    if link_id:
        query = query.where(TrackingEvent.tracking_link_id == link_id)
    if event_type:
        query = query.where(TrackingEvent.event_type == event_type)
    return [{"id": row.id, "link_id": row.tracking_link_id, "alias_id": row.alias_id, "user_id": row.user_id, "telegram_user_id": row.telegram_user_id, "type": row.event_type, "metadata": row.metadata_json, "occurred_at": row.occurred_at} for row in session.scalars(query)]


@app.get("/bot-api/link-rules/{link_id}/events", dependencies=[Depends(require_admin)])
def link_rule_events(link_id: str, session: Session = Depends(get_db)) -> list[dict]:
    if not session.get(TrackingLink, link_id):
        raise HTTPException(404, "Правило не найдено")
    return tracking_events(link_id=link_id, session=session)


@app.get("/bot-api/link-analytics", dependencies=[Depends(require_admin)])
def link_analytics(session: Session = Depends(get_db)) -> dict:
    rules = list_link_rules(session)
    return {"rules": len(rules), "clicks": sum(row["clicks"] for row in rules), "starts": sum(row["starts"] for row in rules), "unique_starts": sum(row["unique_starts"] for row in rules), "items": rules}


@app.get("/bot-api/tags", dependencies=[Depends(require_admin)])
def search_tags(q: str = "", session: Session = Depends(get_db)) -> list[dict]:
    query = select(CrmTag).where(CrmTag.status.in_(["active", "merged"])).order_by(CrmTag.name).limit(100)
    if q:
        query = query.where(CrmTag.name.ilike(f"%{q}%"))
    return [{"id": row.id, "name": row.name, "category": row.category, "status": row.status, "merged_into_tag_id": row.merged_into_tag_id} for row in session.scalars(query)]


@app.get("/bot-api/tags/search", dependencies=[Depends(require_admin)])
def search_tags_alias(q: str = "", session: Session = Depends(get_db)) -> list[dict]:
    return search_tags(q, session)


@app.post("/bot-api/tags", dependencies=[Depends(require_admin)])
def create_tag(body: TagCreateIn, session: Session = Depends(get_db)) -> dict:
    existing = session.scalar(select(CrmTag).where(func.lower(CrmTag.name) == body.name.strip().lower()))
    if existing:
        return {"id": existing.id, "name": existing.name, "created": False}
    row = CrmTag(code=tag_code(body.name), name=body.name.strip(), category="manual", status="active")
    session.add(row); session.commit()
    return {"id": row.id, "name": row.name, "created": True}


@app.post("/bot-api/utm/parse", dependencies=[Depends(require_admin)])
def parse_utm(body: UtmParseIn, session: Session = Depends(get_db)) -> dict:
    result = parse_utm_url(body.url)
    for item in result["parameters"]:
        rule = session.scalar(select(UtmTagRule).where(UtmTagRule.parameter_name == item["name"], UtmTagRule.normalized_value == item["normalized_value"], UtmTagRule.status == "active"))
        tag = session.get(CrmTag, rule.tag_id) if rule else None
        item["mapping"] = {"rule_id": rule.id, "tag_id": tag.id, "tag_name": tag.name} if tag else None
    return result


@app.get("/bot-api/utm/unresolved", dependencies=[Depends(require_admin)])
def unresolved_utm(session: Session = Depends(get_db)) -> list[dict]:
    return unresolved_utm_groups(session)


@app.post("/bot-api/utm/rules", dependencies=[Depends(require_admin)])
def save_utm_rule(body: UtmRuleIn, admin: str = Depends(require_admin), session: Session = Depends(get_db)) -> dict:
    parameter = body.parameter_name.strip().casefold()
    normalized = normalize_value(body.raw_value)
    if not parameter.startswith("utm_"):
        raise HTTPException(422, "Разрешены только параметры utm_*")
    if not session.get(CrmTag, body.tag_id):
        raise HTTPException(422, "Выбранный тег не найден")
    row = session.scalar(select(UtmTagRule).where(UtmTagRule.parameter_name == parameter, UtmTagRule.normalized_value == normalized))
    if row:
        row.raw_value = body.raw_value; row.tag_id = body.tag_id; row.status = "active"; row.created_by = admin
    else:
        row = UtmTagRule(parameter_name=parameter, raw_value=body.raw_value, normalized_value=normalized, tag_id=body.tag_id, created_by=admin)
        session.add(row)
    session.commit()
    return {"id": row.id, "parameter_name": row.parameter_name, "normalized_value": row.normalized_value, "tag_id": row.tag_id}


@app.post("/bot-api/utm/apply", dependencies=[Depends(require_admin)])
def apply_utm_rules(body: dict, session: Session = Depends(get_db)) -> dict:
    preview = bool(body.get("preview", True))
    changed_sessions = changed_events = 0
    for row in session.scalars(select(TrackingEvent).where(TrackingEvent.event_type == "web_click")):
        raw = (row.metadata_json or {}).get("raw_query") or {}
        resolved = exact_utm_matches(session, raw)
        if resolved and (row.metadata_json or {}).get("resolved_tag_ids") != resolved:
            changed_events += 1
            if not preview:
                row.metadata_json = {**(row.metadata_json or {}), "resolved_tag_ids": resolved}
    from app.models import TrackingSession
    for row in session.scalars(select(TrackingSession).where(TrackingSession.consumed_at.is_(None))):
        resolved = exact_utm_matches(session, row.raw_query or {})
        if resolved != list(row.resolved_tag_ids or []):
            changed_sessions += 1
            if not preview:
                row.resolved_tag_ids = resolved
    if not preview:
        session.commit()
    return {"preview": preview, "events": changed_events, "pending_sessions": changed_sessions}


@app.post("/bot-api/utm/apply-preview", dependencies=[Depends(require_admin)])
def preview_utm_rules(session: Session = Depends(get_db)) -> dict:
    return apply_utm_rules({"preview": True}, session)


@app.get("/bot-api/tracking-platforms", dependencies=[Depends(require_admin)])
def tracking_platforms(session: Session = Depends(get_db)) -> list[str]:
    defaults = ["YouTube", "Пикабу", "Яндекс Директ", "Telegram", "ВКонтакте", "Сайт", "Email"]
    existing = [value for value in session.scalars(select(TrackingLink.platform).distinct().order_by(TrackingLink.platform)) if value]
    return list(dict.fromkeys([*defaults, *existing]))


@app.post("/bot-api/broadcasts", dependencies=[Depends(require_admin)])
def create_broadcast(body: BroadcastIn, admin: str = Depends(require_admin), session: Session = Depends(get_db)) -> dict:
    allowed_segment_keys = {"status", "telegram_user_ids", "tag_ids", "product_codes", "access_codes"}
    unknown = set(body.segment) - allowed_segment_keys
    if unknown:
        raise HTTPException(422, f"Неизвестные поля сегмента: {', '.join(sorted(unknown))}")
    segment = dict(body.segment)
    segment.setdefault("status", "active")
    if segment["status"] not in {"active", "maintenance_waitlist"}:
        raise HTTPException(422, "Рассылка разрешена только active или maintenance_waitlist")
    buttons = []
    for button in body.buttons:
        label = str(button.get("text", "")).strip()
        url = str(button.get("url", "")).strip()
        if not label or len(label) > 64 or not url.startswith(("https://", "http://")):
            raise HTTPException(422, "У кнопки нужны текст до 64 символов и http(s)-ссылка")
        buttons.append({"text": label, "url": url})
    segment["_buttons"] = buttons
    _validate_media_reference(body.media_path)
    content = ContentItem(code=f"broadcast_{secrets.token_hex(6)}", title=body.title, body_source=body.text, media_kind=body.media_kind, media_path=body.media_path, labels=["разовая рассылка"], status="ready", origin_system="admin")
    session.add(content); session.flush()
    row = Broadcast(title=body.title, content_item_id=content.id, segment=segment, status="draft", created_by=admin)
    session.add(row); session.commit()
    return {"id":row.id,"status":row.status,"scheduled_at":row.scheduled_at}


@app.get("/bot-api/broadcasts/{broadcast_id}/preview", dependencies=[Depends(require_admin)])
def preview_broadcast(broadcast_id: str, session: Session = Depends(get_db)) -> dict:
    row = session.get(Broadcast, broadcast_id)
    if not row:
        raise HTTPException(404, "Broadcast not found")
    contacts = _broadcast_contacts(session, row)
    return {
        "id": row.id,
        "recipient_count": len(contacts),
        "sample": [
            {"id": contact.id, "telegram_user_id": contact.telegram_user_id, "username": contact.username}
            for contact in contacts[:10]
        ],
        "maintenance_limited": settings.telegram_maintenance_mode,
    }


def _confirm_broadcast_audience(session: Session, row: Broadcast, expected: int) -> int:
    actual = len(_broadcast_contacts(session, row))
    if actual != expected:
        raise HTTPException(409, f"Аудитория изменилась: было подтверждено {expected}, сейчас {actual}. Обновите preview.")
    return actual


@app.post("/bot-api/broadcasts/{broadcast_id}/launch", dependencies=[Depends(require_admin)])
def launch_broadcast(broadcast_id: str, body: BroadcastConfirmIn, session: Session = Depends(get_db)) -> dict:
    row = session.get(Broadcast, broadcast_id)
    if not row:
        raise HTTPException(404, "Broadcast not found")
    if row.status != "draft":
        raise HTTPException(409, "Broadcast already launched")
    _confirm_broadcast_audience(session, row, body.confirmed_recipient_count)
    sent, failed = _deliver_broadcast(session, row, client(), snapshot=True)
    return {"id":row.id,"status":row.status,"sent":sent,"failed":failed}


@app.post("/bot-api/broadcasts/{broadcast_id}/schedule", dependencies=[Depends(require_admin)])
def schedule_broadcast(broadcast_id: str, body: BroadcastScheduleIn, session: Session = Depends(get_db)) -> dict:
    row = session.get(Broadcast, broadcast_id)
    if not row:
        raise HTTPException(404, "Broadcast not found")
    if row.status != "draft":
        raise HTTPException(409, "Планировать можно только draft")
    try:
        scheduled_at = datetime.fromisoformat(body.scheduled_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "Некорректная дата отправки") from None
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    if scheduled_at <= datetime.now(UTC):
        raise HTTPException(422, "Время отправки должно быть в будущем")
    _confirm_broadcast_audience(session, row, body.confirmed_recipient_count)
    _snapshot_broadcast_recipients(session, row)
    row.scheduled_at = scheduled_at
    row.status = "scheduled"
    session.commit()
    return {"id": row.id, "status": row.status, "scheduled_at": row.scheduled_at, "recipients": body.confirmed_recipient_count}


@app.post("/bot-api/broadcasts/{broadcast_id}/test", dependencies=[Depends(require_admin)])
def test_broadcast(broadcast_id: str, body: BroadcastTestIn, admin: str = Depends(require_admin), session: Session = Depends(get_db)) -> dict:
    row = session.get(Broadcast, broadcast_id)
    contact = session.get(Contact, body.contact_id)
    if not row or not contact:
        raise HTTPException(404, "Broadcast or contact not found")
    if contact.telegram_user_id not in allowed_telegram_ids(settings.telegram_maintenance_allowed_user_ids):
        raise HTTPException(409, "Тест рассылки разрешён только owner-аккаунтам")
    content = session.get(ContentItem, row.content_item_id)
    message_id = client().send_content(contact.chat_id, content, {"buttons": (row.segment or {}).get("_buttons", [])})
    session.add(ManualMessage(contact_id=contact.id, direction="out", body_source=f"[Тест рассылки: {row.title}]\n{content.body_source}", status="sent", operator_email=admin, platform_message_id=message_id))
    session.commit()
    return {"status": "sent", "platform_message_id": message_id}


@app.post("/bot-api/broadcasts/{broadcast_id}/retry", dependencies=[Depends(require_admin)])
def retry_broadcast(broadcast_id: str, session: Session = Depends(get_db)) -> dict:
    row = session.get(Broadcast, broadcast_id)
    if not row:
        raise HTTPException(404, "Broadcast not found")
    failed_rows = list(session.scalars(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == row.id, BroadcastRecipient.status == "failed")))
    if not failed_rows:
        raise HTTPException(409, "Нет неудачных доставок для повтора")
    for recipient in failed_rows:
        recipient.status = "pending"
        recipient.error_message = None
    session.flush()
    sent, failed = _deliver_broadcast(session, row, client())
    return {"id": row.id, "status": row.status, "sent": sent, "failed": failed}


@app.get("/bot-api/broadcasts", dependencies=[Depends(require_admin)])
def list_broadcasts(session: Session = Depends(get_db)) -> list[dict]:
    rows = session.execute(select(Broadcast, ContentItem, func.count(BroadcastRecipient.id).filter(BroadcastRecipient.status == "sent"), func.count(BroadcastRecipient.id).filter(BroadcastRecipient.status == "failed")).join(ContentItem, ContentItem.id == Broadcast.content_item_id).outerjoin(BroadcastRecipient, BroadcastRecipient.broadcast_id == Broadcast.id).group_by(Broadcast.id, ContentItem.id).order_by(Broadcast.created_at.desc())).all()
    return [{"id":row.id,"title":row.title,"status":row.status,"scheduled_at":row.scheduled_at,"sent":sent,"failed":failed,"text":content.body_source,"body_source":content.body_source,"media_kind":content.media_kind,"media_path":content.media_path,"segment":{key:value for key,value in (row.segment or {}).items() if key != "_buttons"},"buttons":(row.segment or {}).get("_buttons",[])} for row,content,sent,failed in rows]
