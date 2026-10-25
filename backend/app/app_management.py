"""Scoped client-app management through the owner's native account session."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasicCredentials
from sqlalchemy import String, case, cast, func, or_, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.account_auth_routes import ACCOUNT_MANAGER_EMAIL, native_session_actor, primary_email
from app.auth import admin_identity, security, session_admin
from app.database import get_db
from app.models import DqsState, MetabolismState, StrengthState, TelegramTrackingEvent, User, UserEmail

OWNER_EMAIL = ACCOUNT_MANAGER_EMAIL


def application_manager(request: Request, db: Session) -> str | None:
    admin = session_admin(request)
    if admin:
        return admin
    user = native_session_actor(request, db)
    if user is None or primary_email(db, user.id) != OWNER_EMAIL:
        return None
    if request.method == "GET" and request.url.path == "/api/apps/strength" and request.query_params.get("action") not in {"ping", "openUser", "getWorkout", "getStats", "messengerState"}:
        raise HTTPException(405, "Изменения клиента принимаются только через POST", headers={"Allow": "POST"})
    # This grants app management only, never a general CRM/admin session.
    origin = request.headers.get("origin")
    if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.url.scheme, request.url.netloc):
        raise HTTPException(403, "Недопустимый источник запроса")
    return f"account:{user.id}"


def require_application_manager(request: Request, db: Session = Depends(get_db),
                                credentials: Annotated[HTTPBasicCredentials | None, Depends(security)] = None) -> str:
    manager = admin_identity(request, credentials) or application_manager(request, db)
    if not manager:
        raise HTTPException(401, "Требуется вход владельца приложения или администратора",
                            headers={"WWW-Authenticate": 'Basic realm="Edabalans CRM"'})
    return manager


def managed_user(db: Session, user_id: str | uuid.UUID) -> User:
    try:
        key = uuid.UUID(str(user_id))
    except ValueError:
        raise HTTPException(422, "Некорректный идентификатор клиента") from None
    user = db.get(User, key)
    if user is None or user.merged_into_user_id is not None:
        raise HTTPException(404, "Клиент не найден")
    return user


def client_identity(db: Session, user: User) -> dict:
    return {"user_id": str(user.id), "display_name": user.display_name or "", "email": primary_email(db, user.id)}


def record_application_open(db: Session, user_id: uuid.UUID, app_code: str) -> None:
    """Keep one operational usage summary in the existing shared journey store."""
    key = f"application_activity:{user_id}:{app_code}"
    now = datetime.now(timezone.utc)
    row = db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.deduplication_key == key).with_for_update())
    if row is None:
        try:
            with db.begin_nested():
                db.add(TelegramTrackingEvent(user_id=user_id, event_type="application_activity",
                    deduplication_key=key, occurred_at=now,
                    metadata_json={"app_code": app_code, "first_opened_at": now.isoformat()}))
                db.flush()
            return
        except IntegrityError:
            row = db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.deduplication_key == key).with_for_update())
            if row is None:
                raise
    row.occurred_at = now


def _activity_query(app_code: str):
    event = TelegramTrackingEvent
    first = func.replace(func.coalesce(event.metadata_json["first_opened_at"].as_string(), cast(event.occurred_at, String)), " ", "T")
    summaries = select(event.user_id.label("user_id"), first.label("first_opened_at"), event.occurred_at.label("last_opened_at")).where(
        event.event_type == "application_activity", event.metadata_json["app_code"].as_string() == app_code)
    # Historical page URLs cannot distinguish denied or managed visits after query removal.
    sources = [summaries]
    state = {"dqs": DqsState, "strength": StrengthState, "metabolism": MetabolismState}.get(app_code)
    if state is not None:
        sources.append(select(state.user_id.label("user_id"), func.replace(cast(state.created_at, String), " ", "T").label("first_opened_at"), state.created_at.label("last_opened_at")).where(state.source == "app"))
    history = union_all(*sources).subquery()
    return select(history.c.user_id, func.min(history.c.first_opened_at).label("first_opened_at"),
                  func.max(history.c.last_opened_at).label("last_opened_at")).group_by(history.c.user_id).subquery()


def client_directory(db: Session, q: str, offset: int, *, app_code: str = "account", scope: str = "all", favorite_ids: list[uuid.UUID] | None = None) -> dict:
    activity = _activity_query(app_code)
    favorites = favorite_ids or []
    query = select(User, activity.c.first_opened_at, activity.c.last_opened_at).outerjoin(activity, activity.c.user_id == User.id).where(
        User.merged_into_user_id.is_(None),
        User.id.in_(select(UserEmail.user_id).where(UserEmail.email_normalized != "")),
    )
    if scope != "all":
        used = activity.c.first_opened_at.is_not(None)
        if scope == "active":
            used = used & (activity.c.last_opened_at >= datetime.now(timezone.utc) - timedelta(days=30))
        query = query.where(or_(User.id.in_(favorites), used))
    if q.strip():
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        emails = select(UserEmail.user_id).where(UserEmail.email_normalized.ilike(f"%{term}%", escape="\\"))
        query = query.where(or_(User.display_name.ilike(f"%{term}%", escape="\\"), User.id.in_(emails)))
    rows = db.execute(query.order_by(case((User.id.in_(favorites), 0), else_=1),
        activity.c.last_opened_at.desc().nullslast(), User.display_name, User.id).offset(offset).limit(101)).all()
    result = []
    def stamp(value):
        if value is None:
            return None
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).isoformat()
    for user, first, last in rows[:100]:
        result.append({**client_identity(db, user), "has_opened_app": first is not None,
            "first_opened_at": stamp(first), "last_opened_at": stamp(last)})
    return {"ok": True, "users": result, "more": len(rows) > 100}
