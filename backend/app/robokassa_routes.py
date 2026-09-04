from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.intensive_web_access import offer_user_id
from app.models import Payment
from app.pricing_routes import enforce_preview_checkout_rate_limit
from app.pricing_service import active_pricing_version
from app.robokassa_service import RobokassaError, confirm_payment, create_payment


router = APIRouter(tags=["payments"])


class RobokassaCheckoutIn(BaseModel):
    price_code: str = Field(min_length=3, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    intensive_offer: str | None = Field(default=None, max_length=1024)


def _enforce_checkout_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "checkout origin required")
    origin_host = (urlsplit(origin).hostname or "").lower()
    request_host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    allowed_hosts = {
        (urlsplit(item).hostname or "").lower() for item in settings.allowed_origins_list
    }
    allowed_hosts.update({"app.edabalans.ru", request_host})
    if origin_host not in allowed_hosts:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "checkout origin rejected")


@router.post("/api/payments/robokassa/checkout")
def robokassa_checkout(
    body: RobokassaCheckoutIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    _enforce_checkout_origin(request, settings)
    enforce_preview_checkout_rate_limit(request)
    version = active_pricing_version(db)
    if version is None:
        raise HTTPException(503, "Активная версия цен не опубликована")
    discount_user_id: uuid.UUID | None = None
    if body.intensive_offer:
        discount_user_id = offer_user_id(db, body.intensive_offer)
        if discount_user_id is None:
            raise HTTPException(403, "Персональная скидка истекла или недействительна")
    try:
        return create_payment(
            db,
            settings,
            version,
            body.price_code,
            body.email,
            offer_user_id=discount_user_id,
        )
    except RobokassaError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.post("/integrations/robokassa/result2", include_in_schema=False)
async def robokassa_result2(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlainTextResponse:
    body = await request.body()
    if len(body) > 65_536:
        raise HTTPException(413, "ResultUrl2 is too large")
    try:
        invoice_id = confirm_payment(db, settings, body.decode("ascii"))
    except (UnicodeDecodeError, RobokassaError) as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return PlainTextResponse(f"OK{invoice_id}")


@router.get("/api/payments/robokassa/{invoice_id}/status")
def robokassa_status(
    invoice_id: str,
    db: Session = Depends(get_db),
) -> dict:
    payment = db.scalar(
        select(Payment).where(
            Payment.source == "robokassa",
            Payment.external_order_id == invoice_id,
        )
    )
    if payment is None:
        raise HTTPException(404, "Счёт не найден")
    return {"ok": True, "invoice_id": invoice_id, "status": payment.payment_status}


def _return_page(title: str, message: str, *, invoice_id: str | None = None) -> HTMLResponse:
    polling = ""
    if invoice_id and invoice_id.isdigit():
        polling = f"""<script>
const statusUrl='/api/payments/robokassa/{invoice_id}/status';
async function check(){{try{{const r=await fetch(statusUrl,{{credentials:'omit'}});const d=await r.json();if(d.status==='paid'){{document.getElementById('state').textContent='Оплата подтверждена.';return;}}if(d.status==='test_paid'){{document.getElementById('state').textContent='Тестовая оплата подтверждена.';return;}}}}catch(e){{}}setTimeout(check,2000);}}check();
</script>"""
    return HTMLResponse(f"""<!doctype html><html lang=\"ru\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"robots\" content=\"noindex,nofollow\"><title>{title}</title><style>body{{margin:0;min-height:100svh;display:grid;place-items:center;background:#eef8ff;color:#173f70;font:16px/1.5 Arial,sans-serif}}main{{max-width:560px;margin:20px;padding:32px;border-radius:24px;background:white;box-shadow:0 20px 60px #176ba326;text-align:center}}a{{color:#167bc0}}</style><main><h1>{title}</h1><p id=\"state\">{message}</p><p><a href=\"/preview/homepage-mobile#pricing\">Вернуться на сайт</a></p></main>{polling}</html>""", headers={"X-Robots-Tag": "noindex, nofollow"})


@router.get("/payments/robokassa/success", include_in_schema=False)
def robokassa_success(InvId: str | None = Query(default=None)) -> HTMLResponse:
    return _return_page(
        "Проверяем оплату",
        "Robokassa приняла платёж. Ждём подтверждение от платёжного сервера…",
        invoice_id=InvId,
    )


@router.get("/payments/robokassa/fail", include_in_schema=False)
def robokassa_fail() -> HTMLResponse:
    return _return_page("Оплата не завершена", "Деньги не списаны. Можно вернуться и попробовать ещё раз.")
