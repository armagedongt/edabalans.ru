from __future__ import annotations

from decimal import Decimal
from html import escape
import json
from pathlib import Path
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.account_auth_routes import primary_email, require_native_user
from app.intensive_web_access import offer_user_id
from app.masterclass_routes import build_offers, create_offer_checkout_record
from app.models import Payment, Resource, UserAccess
from app.pricing_routes import enforce_preview_checkout_rate_limit
from app.pricing_service import (
    active_pricing_version,
    pricing_entry_map,
    site_tariff_amount,
)
from app.robokassa_service import (
    RobokassaError,
    SUCCESS_KIND_MANUAL_SERVICE,
    SUCCESS_KIND_MEMBER_OFFER,
    SUCCESS_KIND_PUBLIC_MASTERCLASS,
    confirm_payment,
    create_live_probe_payment,
    create_manual_service_payment,
    create_member_offer_payment,
    create_payment,
)
from app.robokassa_subscription_service import (
    SUCCESS_KIND_SUBSCRIPTION,
    cancel_subscription,
    create_subscription_payment,
    public_subscription_offer,
    serialize_subscription,
    subscription_for_user,
)


router = APIRouter(tags=["payments"])
GO_PAYMENT_HOSTS = {
    "go.похудение-это-есть.рф",
    "go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
}
GO_TEST_PRICE_CODE = "site.masterclass.basic"
MANUAL_PAYMENT_PAGE = Path(__file__).with_name("static") / "manual-payment.html"
SUBSCRIPTION_PAGE = Path(__file__).with_name("static") / "coaching-subscription.html"

SUCCESS_CONTENT = {
    SUCCESS_KIND_PUBLIC_MASTERCLASS: {
        "title": "Оплата прошла успешно!",
        "html": (
            "<p>Проверьте почту, на которую оформляли заказ.</p>"
            "<p>Туда отправлен чек о покупке. В течение нескольких минут туда придут данные для входа в личный кабинет и ссылка на него.</p>"
            "<p>Если письма нет, проверьте папку «Спам».</p>"
            "<p>При любых технических проблемах напишите мне: <a href=\"https://t.me/FitnessSergey\">в Telegram</a> или <a href=\"https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw\">в MAX</a>.</p>"
        ),
    },
    SUCCESS_KIND_MANUAL_SERVICE: {
        "title": "Оплата прошла успешно!",
        "html": (
            "<p>Чек о покупке отправлен вам на почту, которую вы указали при оплате.</p>"
            "<p>Мне тоже придёт уведомление об оплате, но вы можете сразу написать мне: <a href=\"https://t.me/FitnessSergey\">в Telegram</a> или <a href=\"https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw\">в MAX</a>.</p>"
        ),
    },
    SUCCESS_KIND_MEMBER_OFFER: {
        "title": "Оплата прошла успешно!",
        "html": (
            "<p>Чек о покупке отправлен вам на почту, которую вы указали при оплате.</p>"
            "<p>Доступ к приобретённым материалам проверяйте в <a href=\"/lk\">личном кабинете</a>.</p>"
            "<p>Если вы оплачивали консультацию или курс, который открывается после прохождения другого курса, и хотите уточнить сроки — напишите мне: <a href=\"https://t.me/FitnessSergey\">в Telegram</a> или <a href=\"https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw\">в MAX</a>.</p>"
        ),
    },
    SUCCESS_KIND_SUBSCRIPTION: {
        "title": "Первый месяц сопровождения оплачен!",
        "html": (
            "<p>Подписка активна. Следующее списание произойдёт через месяц по той же цене.</p>"
            "<p>Управлять подпиской и отключить будущие списания можно на "
            "<a href=\"/subscription\">странице подписки</a> после входа в ваш аккаунт.</p>"
            "<p>Если нужен быстрый ответ, напишите мне "
            "<a href=\"https://t.me/FitnessSergey\">в Telegram</a>.</p>"
        ),
    },
}


def _success_kind(payment: Payment) -> str:
    payload = payment.raw_payload or {}
    kind = payload.get("success_kind")
    if kind in SUCCESS_CONTENT:
        return str(kind)
    if payload.get("account_purchase"):
        return SUCCESS_KIND_MEMBER_OFFER
    return SUCCESS_KIND_PUBLIC_MASTERCLASS
GO_TEST_EMAIL = "robokassa-test@pohudenie-eto-est.invalid"


class RobokassaCheckoutIn(BaseModel):
    price_code: str = Field(min_length=3, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    intensive_offer: str | None = Field(default=None, max_length=1024)


class NativeOfferCheckoutIn(BaseModel):
    offer_code: str = Field(min_length=3, max_length=120)
    focus_product_code: str | None = Field(default=None, max_length=40)


class NativeTariffCheckoutIn(BaseModel):
    price_code: str = Field(min_length=3, max_length=120)


class ManualPaymentCheckoutIn(BaseModel):
    amount: Decimal = Field(gt=0, le=10_000_000, max_digits=14, decimal_places=2)
    payer_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    comment: str = Field(min_length=1, max_length=1000)


class SubscriptionCheckoutIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    accept_terms: bool


def _require_go_test_host(request: Request) -> None:
    host = (request.url.hostname or "").lower()
    if host not in GO_PAYMENT_HOSTS and host != "testserver":
        raise HTTPException(status.HTTP_404_NOT_FOUND)


def _go_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def _go_test_settings(request: Request, settings: Settings) -> Settings:
    origin = _go_origin(request)
    return settings.model_copy(
        update={
            "robokassa_result_url_2": f"{origin}/integrations/robokassa/result2",
            "robokassa_success_url_2": f"{origin}/payments/robokassa/success",
            "robokassa_fail_url_2": f"{origin}/payments/robokassa/fail",
        }
    )


def _go_live_probe_settings(request: Request, settings: Settings) -> Settings:
    origin = _go_origin(request)
    return settings.model_copy(
        update={
            "robokassa_test_mode": False,
            "robokassa_result_url_2": f"{origin}/integrations/robokassa/result2",
            "robokassa_success_url_2": f"{origin}/payments/robokassa/live-probe-success",
            "robokassa_fail_url_2": f"{origin}/payments/robokassa/live-probe-fail",
        }
    )


@router.get("/pay", include_in_schema=False)
def manual_payment_page() -> FileResponse:
    return FileResponse(
        MANUAL_PAYMENT_PAGE,
        media_type="text/html; charset=utf-8",
        headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-cache"},
    )


@router.get("/subscription", include_in_schema=False)
@router.get("/subscription/", include_in_schema=False)
def coaching_subscription_page() -> FileResponse:
    return FileResponse(
        SUBSCRIPTION_PAGE,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/api/payments/robokassa/subscription/offer")
def robokassa_subscription_offer(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not settings.robokassa_recurring_worker_enabled:
        raise HTTPException(503, "Подписка пока не опубликована")
    version = active_pricing_version(db)
    if version is None:
        raise HTTPException(503, "Активная версия цен не опубликована")
    try:
        return public_subscription_offer(db, version)
    except RobokassaError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/api/payments/robokassa/subscription/checkout")
def robokassa_subscription_checkout(
    body: SubscriptionCheckoutIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    _enforce_checkout_origin(request, settings)
    enforce_preview_checkout_rate_limit(request)
    if not settings.robokassa_recurring_worker_enabled:
        raise HTTPException(503, "Подписка пока не опубликована")
    if not body.accept_terms:
        raise HTTPException(422, "Нужно принять условия подписки и обработки данных")
    version = active_pricing_version(db)
    if version is None:
        raise HTTPException(503, "Активная версия цен не опубликована")
    try:
        return create_subscription_payment(
            db,
            settings,
            version,
            body.email,
            terms_ip=request.client.host if request.client else None,
            terms_user_agent=request.headers.get("user-agent"),
        )
    except RobokassaError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/payments/robokassa/subscription/mine")
def robokassa_my_subscription(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = require_native_user(request, db)
    return {"ok": True, "subscription": serialize_subscription(subscription_for_user(db, user))}


@router.post("/api/payments/robokassa/subscription/cancel")
def robokassa_cancel_subscription(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    _enforce_checkout_origin(request, settings)
    user = require_native_user(request, db)
    try:
        row = cancel_subscription(db, user)
    except RobokassaError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "subscription": serialize_subscription(row)}


def _robokassa_redirect(payment_form: dict) -> RedirectResponse:
    action = str(payment_form["action"])
    separator = "&" if "?" in action else "?"
    payment_url = f'{action}{separator}{urlencode(payment_form["fields"])}'
    return RedirectResponse(payment_url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/robokassa-test", include_in_schema=False)
def robokassa_go_test_page(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    _require_go_test_host(request)
    if not settings.robokassa_test_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    version = active_pricing_version(db)
    if version is None:
        raise HTTPException(503, "Активная версия цен не опубликована")
    entry = pricing_entry_map(db, version).get(GO_TEST_PRICE_CODE)
    if entry is None or not entry.enabled:
        raise HTTPException(503, "Тестовый тариф недоступен")
    amount = site_tariff_amount(entry)
    amount_label = f"{amount:,.0f}".replace(",", " ")
    return HTMLResponse(
        "<!doctype html><html lang=\"ru\"><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        "<title>Проверка оплаты</title>"
        "<style>body{margin:0;min-height:100svh;display:grid;place-items:center;"
        "background:#f1f9ff;font-family:Arial,sans-serif}"
        "button{padding:18px 28px;border:0;border-radius:16px;background:#159ee4;"
        "color:#fff;font-size:18px;font-weight:700;cursor:pointer;"
        "box-shadow:0 12px 30px #159ee444}</style>"
        '<form action="/robokassa-test/start" method="POST">'
        f'<button type="submit">Проверить оплату · {amount_label} ₽</button>'
        "</form></html>",
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )


@router.post("/robokassa-test/start", include_in_schema=False)
def robokassa_go_test_start(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    _require_go_test_host(request)
    if not settings.robokassa_test_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    enforce_preview_checkout_rate_limit(request)
    version = active_pricing_version(db)
    if version is None:
        raise HTTPException(503, "Активная версия цен не опубликована")
    try:
        checkout = create_payment(
            db,
            _go_test_settings(request, settings),
            version,
            GO_TEST_PRICE_CODE,
            GO_TEST_EMAIL,
        )
    except RobokassaError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return _robokassa_redirect(checkout["payment_form"])


@router.get("/robokassa-live-probe", include_in_schema=False)
def robokassa_live_probe_page(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    _require_go_test_host(request)
    if not settings.robokassa_live_probe_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return HTMLResponse(
        "<!doctype html><html lang=\"ru\"><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        "<title>Реальная проверка Robokassa</title>"
        "<style>body{margin:0;min-height:100svh;display:grid;place-items:center;"
        "background:#f1f9ff;color:#173f70;font:16px/1.5 Arial,sans-serif}"
        "main{width:min(440px,calc(100% - 40px));padding:30px;box-sizing:border-box;"
        "border-radius:24px;background:#fff;box-shadow:0 20px 60px #176ba326}"
        "h1{font-size:25px;line-height:1.15;margin:0 0 12px}p{margin:0 0 18px}"
        "label{display:block;font-weight:700;margin-bottom:6px}input{width:100%;"
        "box-sizing:border-box;padding:14px;border:1px solid #9bc7e3;border-radius:12px;"
        "font:inherit;margin-bottom:14px}button{width:100%;padding:16px;border:0;"
        "border-radius:14px;background:#159ee4;color:#fff;font-size:18px;font-weight:700;"
        "cursor:pointer;box-shadow:0 12px 30px #159ee444}.note{font-size:14px;color:#526f8f}"
        "</style><main><h1>Реальная оплата 10 ₽</h1>"
        "<p>Отдельная техническая проверка прямой связи с Robokassa. Это настоящий платёж.</p>"
        '<form action="/robokassa-live-probe/start" method="POST">'
        '<label for="email">Email для чека</label>'
        '<input id="email" name="email" type="email" autocomplete="email" required '
        'maxlength="320" placeholder="name@example.ru">'
        '<button type="submit">Перейти к оплате · 10 ₽</button></form>'
        '<p class="note">Покупательский аккаунт, доступ к курсу и письмо этой проверкой не создаются.</p>'
        "</main></html>",
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )


@router.post("/robokassa-live-probe/start", include_in_schema=False)
async def robokassa_live_probe_start(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    _require_go_test_host(request)
    if not settings.robokassa_live_probe_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    _enforce_checkout_origin(request, settings)
    enforce_preview_checkout_rate_limit(request)
    if not request.headers.get("content-type", "").lower().startswith(
        "application/x-www-form-urlencoded"
    ):
        raise HTTPException(415, "Ожидается форма оплаты")
    body = await request.body()
    if len(body) > 4096:
        raise HTTPException(413, "Форма оплаты слишком большая")
    try:
        email = parse_qs(body.decode("utf-8"), keep_blank_values=True).get("email", [""])[0]
        checkout = create_live_probe_payment(
            db,
            _go_live_probe_settings(request, settings),
            email,
        )
    except (UnicodeDecodeError, RobokassaError) as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return _robokassa_redirect(checkout["payment_form"])


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


@router.post("/api/payments/robokassa/manual-checkout")
def robokassa_manual_checkout(
    body: ManualPaymentCheckoutIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    _enforce_checkout_origin(request, settings)
    enforce_preview_checkout_rate_limit(request)
    try:
        return create_manual_service_payment(
            db, settings, body.amount, body.payer_name, body.email, body.comment
        )
    except RobokassaError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.post("/api/payments/robokassa/account-tariffs/checkout")
def robokassa_account_tariff_checkout(
    body: NativeTariffCheckoutIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    _enforce_checkout_origin(request, settings)
    enforce_preview_checkout_rate_limit(request)
    user = require_native_user(request, db)
    already_owned = db.scalar(
        select(UserAccess.id)
        .join(Resource, Resource.id == UserAccess.resource_id)
        .where(UserAccess.user_id == user.id, Resource.code == "ACCESS_MASTERCLASS", UserAccess.revoked_at.is_(None))
    )
    if already_owned is not None:
        raise HTTPException(409, "Мастер-класс уже доступен в личном кабинете")
    version = active_pricing_version(db)
    if version is None:
        raise HTTPException(503, "Активная версия цен не опубликована")
    try:
        return create_payment(
            db, settings, version, body.price_code, primary_email(db, user.id), account_user=user
        )
    except RobokassaError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.post("/api/payments/robokassa/account-offers/checkout")
def robokassa_account_offer_checkout(
    body: NativeOfferCheckoutIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    _enforce_checkout_origin(request, settings)
    enforce_preview_checkout_rate_limit(request)
    user = require_native_user(request, db)
    payload = build_offers(
        db, user, "offers-hub", use_pricing_catalog=settings.pricing_catalog_enabled,
        focus_product_code=body.focus_product_code, readonly=True,
    )
    card = next((item for item in payload["offers"] if item["code"] == body.offer_code), None)
    if card is None:
        raise HTTPException(409, "Предложение больше не доступно")
    try:
        checkout = create_offer_checkout_record(db, user, payload, card)
        return create_member_offer_payment(db, settings, checkout, user, primary_email(db, user.id))
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
    return {
        "ok": True,
        "invoice_id": invoice_id,
        "status": payment.payment_status,
        "success_kind": _success_kind(payment),
    }


def _return_page(
    title: str,
    message: str,
    *,
    invoice_id: str | None = None,
    return_url: str | None = "/preview/homepage-release-candidate#pricing",
    success_kind: str | None = None,
) -> HTMLResponse:
    polling = ""
    if invoice_id and invoice_id.isdigit():
        polling = f"""<script>
const statusUrl='/api/payments/robokassa/{invoice_id}/status';
const successContent={json.dumps(SUCCESS_CONTENT, ensure_ascii=False)};
function showPaid(kind){{const content=successContent[kind]||successContent[{json.dumps(SUCCESS_KIND_PUBLIC_MASTERCLASS)}];document.title=content.title;document.getElementById('payment-page-title').textContent=content.title;document.getElementById('state').innerHTML=content.html;}}
async function check(){{try{{const r=await fetch(statusUrl,{{credentials:'omit'}});const d=await r.json();if(d.status==='paid'){{showPaid(d.success_kind);return;}}if(d.status==='test_paid'){{document.getElementById('state').textContent='Тестовая оплата подтверждена.';return;}}}}catch(e){{}}setTimeout(check,2000);}}check();
</script>"""
    if success_kind:
        content = SUCCESS_CONTENT[success_kind]
        title = content["title"]
        message = content["html"]
    return_link = (
        f'<p><a href="{escape(return_url, quote=True)}">Вернуться на сайт</a></p>'
        if return_url else ""
    )
    return HTMLResponse(f"""<!doctype html><html lang=\"ru\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"robots\" content=\"noindex,nofollow\"><title>{title}</title><style>body{{margin:0;min-height:100svh;display:grid;place-items:center;background:#eef8ff;color:#173f70;font:16px/1.5 Arial,sans-serif}}main{{max-width:560px;margin:20px;padding:32px;border-radius:24px;background:white;box-shadow:0 20px 60px #176ba326;text-align:left}}a{{color:#167bc0}}#state p{{margin:0 0 14px}}#state p:last-child{{margin-bottom:0}}</style><main><h1 id=\"payment-page-title\">{title}</h1><div id=\"state\">{message}</div>{return_link}</main>{polling}</html>""", headers={"X-Robots-Tag": "noindex, nofollow"})


@router.get("/payments/robokassa/success", include_in_schema=False)
def robokassa_success(
    InvId: str | None = Query(default=None),
) -> HTMLResponse:
    return _return_page(
        "Проверяем оплату",
        "Robokassa приняла платёж. Ждём подтверждение от платёжного сервера…",
        invoice_id=InvId,
        return_url=None,
    )


@router.get("/preview/robokassa-success", include_in_schema=False)
def robokassa_success_preview() -> HTMLResponse:
    return _return_page(
        "Оплата прошла успешно!",
        "",
        return_url=None,
        success_kind=SUCCESS_KIND_PUBLIC_MASTERCLASS,
    )


@router.get("/preview/robokassa-success/manual-service", include_in_schema=False)
def robokassa_manual_service_success_preview() -> HTMLResponse:
    return _return_page(
        "Оплата прошла успешно!",
        "",
        return_url=None,
        success_kind=SUCCESS_KIND_MANUAL_SERVICE,
    )


@router.get("/preview/robokassa-success/member-offer", include_in_schema=False)
def robokassa_member_offer_success_preview() -> HTMLResponse:
    return _return_page(
        "Оплата прошла успешно!",
        "",
        return_url=None,
        success_kind=SUCCESS_KIND_MEMBER_OFFER,
    )


@router.get("/payments/robokassa/fail", include_in_schema=False)
def robokassa_fail(request: Request) -> HTMLResponse:
    return _return_page(
        "Оплата не завершена",
        "Деньги не списаны. Можно вернуться и попробовать ещё раз.",
        return_url=(
            "/robokassa-test"
            if (request.url.hostname or "").lower() in GO_PAYMENT_HOSTS
            else "/preview/homepage-release-candidate#pricing"
        ),
    )


@router.get("/payments/robokassa/live-probe-success", include_in_schema=False)
def robokassa_live_probe_success(
    request: Request,
    InvId: str | None = Query(default=None),
) -> HTMLResponse:
    _require_go_test_host(request)
    return _return_page(
        "Проверяем реальную оплату",
        "Robokassa приняла платёж. Ждём серверное подтверждение ResultUrl2…",
        invoice_id=InvId,
        return_url="/robokassa-live-probe",
    )


@router.get("/payments/robokassa/live-probe-fail", include_in_schema=False)
def robokassa_live_probe_fail(request: Request) -> HTMLResponse:
    _require_go_test_host(request)
    return _return_page(
        "Оплата не завершена",
        "Деньги не списаны. Можно вернуться и попробовать ещё раз.",
        return_url="/robokassa-live-probe",
    )
