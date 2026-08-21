import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings

security = HTTPBasic(auto_error=False)


def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str:
    settings = get_settings()
    configured = bool(settings.admin_username and settings.admin_password)
    valid = bool(
        configured
        and credentials
        and secrets.compare_digest(credentials.username, settings.admin_username)
        and secrets.compare_digest(credentials.password, settings.admin_password)
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Edabalans CRM"'},
        )
    return settings.admin_username
