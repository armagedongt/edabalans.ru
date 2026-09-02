from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.security import HTTPBasicCredentials
from sqlalchemy.orm import Session

from app.auth import admin_identity, require_admin, security
from app.config import get_settings
from app.database import get_db
from app.marketing_service import marketing_dashboard


router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parent / "static"
EARLIEST_REPORT_DATE = date(2025, 12, 1)


@router.get("/admin/marketing", include_in_schema=False)
def marketing_page(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> Response:
    if not admin_identity(request, credentials):
        return RedirectResponse("/admin?next=/admin/marketing", status_code=303)
    response = FileResponse(STATIC_DIR / "admin.html")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/admin/api/marketing/overview")
def marketing_overview(
    date_from: date = Query(default=EARLIEST_REPORT_DATE, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    date_to = date_to or datetime.now(ZoneInfo("Europe/Moscow")).date()
    if date_from < EARLIEST_REPORT_DATE:
        raise HTTPException(400, detail="Данные до декабря 2025 года не входят в эту админку")
    if date_to < date_from:
        raise HTTPException(400, detail="Дата окончания раньше даты начала")
    if (date_to - date_from).days > 730:
        raise HTTPException(400, detail="Период не может быть длиннее двух лет")
    return marketing_dashboard(
        db,
        get_settings(),
        date_from=date_from,
        date_to=date_to,
    )
