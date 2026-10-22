"""Scoped client-app management through the owner's native account session."""
from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasicCredentials
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.account_auth_routes import native_session_user, primary_email
from app.auth import admin_identity, security, session_admin
from app.database import get_db
from app.models import User, UserEmail

OWNER_EMAIL = "armagedongt@gmail.com"


def application_manager(request: Request, db: Session) -> str | None:
    admin = session_admin(request)
    if admin:
        return admin
    user = native_session_user(request, db)
    if user is None or primary_email(db, user.id) != OWNER_EMAIL:
        return None
    if request.method == "GET" and request.url.path == "/api/apps/strength" and request.query_params.get("action") not in {"ping", "openUser", "getWorkout", "getStats"}:
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


def client_directory(db: Session, q: str, offset: int) -> dict:
    query = select(User).where(User.merged_into_user_id.is_(None))
    if q.strip():
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        emails = select(UserEmail.user_id).where(UserEmail.email_normalized.ilike(f"%{term}%", escape="\\"))
        query = query.where(or_(User.display_name.ilike(f"%{term}%", escape="\\"), User.id.in_(emails)))
    users = db.scalars(query.order_by(User.display_name, User.id).offset(offset).limit(101)).all()
    return {"ok": True, "users": [client_identity(db, user) for user in users[:100]], "more": len(users) > 100}
