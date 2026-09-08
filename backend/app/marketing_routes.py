import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.security import HTTPBasicCredentials
from sqlalchemy.orm import Session

from app.auth import admin_identity, require_admin, security
from app.config import get_settings
from app.database import get_db
from app.marketing_daily_report import generate_and_store
from app.marketing_service import marketing_dashboard
from app.models import MarketingDailyReport
from sqlalchemy import select


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
    source: str | None = Query(default=None, max_length=255),
    campaign: str | None = Query(default=None, max_length=255),
    creative: str | None = Query(default=None, max_length=255),
    user: str | None = Query(default=None, max_length=255),
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
        source_filter=source,
        campaign_filter=campaign,
        creative_filter=creative,
        user_query=user,
    )


def _require_report_token(request: Request) -> None:
    configured = get_settings().marketing_report_token
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not configured or not secrets.compare_digest(configured, supplied):
        raise HTTPException(404, detail="Not found")


@router.post("/api/internal/marketing/daily-report/generate")
def generate_marketing_daily_report(
    request: Request,
    report_date: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict:
    _require_report_token(request)
    target = report_date or (datetime.now(ZoneInfo("Europe/Moscow")).date() - timedelta(days=1))
    row = generate_and_store(db, get_settings(), target)
    return {"date": row.report_date, "status": row.delivery_status, "messages": row.telegram_messages}


@router.get("/api/internal/marketing/daily-report")
def get_marketing_daily_report(
    request: Request,
    report_date: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict:
    _require_report_token(request)
    query = select(MarketingDailyReport)
    if report_date:
        query = query.where(MarketingDailyReport.report_date == report_date.isoformat())
    else:
        query = query.order_by(MarketingDailyReport.report_date.desc())
    row = db.scalar(query)
    if row is None:
        raise HTTPException(404, detail="Report not generated")
    return {"date": row.report_date, "status": row.delivery_status, "messages": row.telegram_messages, "payload": row.payload_json}


@router.post("/api/internal/marketing/daily-report/delivered")
def mark_marketing_daily_report_delivered(
    request: Request,
    report_date: date = Query(alias="date"),
    db: Session = Depends(get_db),
) -> dict:
    _require_report_token(request)
    row = db.scalar(select(MarketingDailyReport).where(MarketingDailyReport.report_date == report_date.isoformat()))
    if row is None:
        raise HTTPException(404, detail="Report not generated")
    row.delivery_status = "sent"
    row.sent_at = datetime.now(timezone.utc)
    row.delivery_error = None
    db.commit()
    return {"date": row.report_date, "status": "sent"}


@router.get("/admin/api/marketing/reports/latest")
def latest_marketing_daily_report(
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    row = db.scalar(select(MarketingDailyReport).order_by(MarketingDailyReport.report_date.desc()))
    if row is None:
        raise HTTPException(404, detail="Отчёты ещё не сформированы")
    return row.payload_json
