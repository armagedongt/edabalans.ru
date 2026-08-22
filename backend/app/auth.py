import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings

security = HTTPBasic(auto_error=False)
ADMIN_COOKIE = "edabalans_admin"
ADMIN_SESSION_SECONDS = 60 * 60 * 24 * 7


def admin_session_token(username: str, expires_at: int) -> str:
    settings = get_settings()
    payload = base64.urlsafe_b64encode(f"{username}|{expires_at}".encode()).decode().rstrip("=")
    signature = hmac.new(settings.admin_password.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def session_admin(request: Request) -> str | None:
    settings = get_settings()
    token = request.cookies.get(ADMIN_COOKIE, "")
    try:
        payload, signature = token.rsplit(".", 1)
        expected = hmac.new(settings.admin_password.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(signature, expected):
            return None
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
        username, expires_at = decoded.rsplit("|", 1)
        if username != settings.admin_username or int(expires_at) < int(time.time()):
            return None
        return username
    except (ValueError, UnicodeDecodeError):
        return None


def valid_admin_credentials(username: str, password: str) -> bool:
    settings = get_settings()
    return bool(
        settings.admin_username
        and settings.admin_password
        and secrets.compare_digest(username.strip().lower(), settings.admin_username.lower())
        and secrets.compare_digest(password, settings.admin_password)
    )


def admin_identity(
    request: Request,
    credentials: HTTPBasicCredentials | None = None,
) -> str | None:
    settings = get_settings()
    cookie_username = session_admin(request)
    if cookie_username:
        return cookie_username
    if credentials and valid_admin_credentials(credentials.username, credentials.password):
        return settings.admin_username
    return None


def require_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str:
    identity = admin_identity(request, credentials)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Edabalans CRM"'},
        )
    return identity
