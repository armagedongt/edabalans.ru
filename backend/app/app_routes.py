from __future__ import annotations

import json
import math
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.app_service import (
    AppAccessError,
    normalize_email,
    primary_email,
    resolve_user_for_resource,
    utc_iso,
)
from app.auth import require_admin, session_admin
from app.database import get_db
from app.legal_service import legal_status_payload
from app.intensive_public_cta import INTENSIVE_PUBLIC_CTA
from app.intensive_web_access import (
    access_token_row,
    attributed_path,
    create_offer_token,
    current_day,
    day_unlocked,
    mark_assignment_opened,
    offer_for_user,
    open_day,
    progress_rows,
    record_entry_attribution,
    session_identity,
    set_session,
    state_payload,
)
from app.config import Settings, get_settings
from app.models import (
    AdminAppEdit,
    DqsState,
    MessengerAccount,
    MetabolismState,
    Resource,
    StrengthExercise,
    StrengthState,
    User,
    UserAccess,
    MasterclassEvent,
)


router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parent / "static"
DAY_COUNT = 30
CATEGORY_COUNT = 17
JSONP_CALLBACK = re.compile(r"^[A-Za-z_$][0-9A-Za-z_$]*$")
HOMEPAGE_MOBILE_PREVIEW_ASSETS = {
    "crying-character.png",
    "final-cta-cat-clock.webp",
    "max-full-colored-dark-official.png",
    "max-full-colored-official.png",
    "money-bag-ruble-v1.webp",
    "montserrat-cyrillic.woff2",
    "montserrat-latin.woff2",
    "media-coordinator.js",
    "masterclass-inside-01.webp",
    "masterclass-inside-02.webp",
    "masterclass-inside-03.webp",
    "masterclass-inside-04.webp",
    "reviews-promo-before-after.jpg",
    "reviews-promo-can-dont-want.jpg",
    "reviews-promo-cant-do.jpg",
    "reviews-promo-hudet-budem.jpg",
    "reviews-promo-time-cat.png",
    "vsl-player.html",
    "weight-loss-after-masterclass.svg",
    "weight-loss-before-masterclass.svg",
}


def public_asset(path: Path, stable_loader: bool = False) -> FileResponse:
    response = FileResponse(path)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = "no-cache" if stable_loader else "public, max-age=300"
    return response


def homepage_library_fragment(source: str, name: str) -> str:
    start_marker = f"<!-- library:{name}:start -->"
    end_marker = f"<!-- library:{name}:end -->"
    start = source.index(start_marker) + len(start_marker)
    end = source.index(end_marker, start)
    return source[start:end].strip()


@router.get("/embed.js", include_in_schema=False)
def embed_loader() -> FileResponse:
    return public_asset(STATIC_DIR / "embed.js", stable_loader=True)


@router.get("/homepage.js", include_in_schema=False)
def homepage_loader() -> FileResponse:
    return public_asset(STATIC_DIR / "homepage.js", stable_loader=True)


@router.get("/preview/homepage-tilda-shell", include_in_schema=False)
def homepage_tilda_shell_preview() -> FileResponse:
    response = public_asset(
        STATIC_DIR / "homepage-tilda-shell.html",
        stable_loader=True,
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.get("/site-footer.js", include_in_schema=False)
def site_footer_loader() -> FileResponse:
    return public_asset(STATIC_DIR / "site-footer.js", stable_loader=True)


@router.get("/site-header.js", include_in_schema=False)
def site_header_loader() -> FileResponse:
    return public_asset(STATIC_DIR / "site-header.js", stable_loader=True)


@router.get("/preview/homepage-recognition", include_in_schema=False)
def homepage_recognition_preview() -> HTMLResponse:
    source = (STATIC_DIR / "homepage-preview" / "mobile.html").read_text(
        encoding="utf-8"
    )
    head = source[: source.index('<body data-page-theme="blue-mist">')]

    template = head.replace(
        "<title>Новая главная — мобильная цепочка принятых блоков</title>",
        "<title>Библиотека блоков · Человечек и облачка</title>",
        1,
    ) + (
        '<body data-page-theme="blue-mist" data-library-block="recognition" '
        'data-library-status="accepted">\n'
        '<main class="homepage-chain">\n'
        f'{homepage_library_fragment(source, "recognition")}\n'
        '</main>\n'
        f'{homepage_library_fragment(source, "recognition-script")}\n'
        '</body>\n</html>\n'
    )
    response = HTMLResponse(template, headers={"Cache-Control": "no-cache"})
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.get("/preview/app-visual-catalog", include_in_schema=False)
def app_visual_catalog_preview() -> FileResponse:
    response = public_asset(
        STATIC_DIR / "app-visual-catalog" / "index.html",
        stable_loader=True,
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.get(
    "/preview/homepage-recognition/crying-character.png",
    include_in_schema=False,
)
def homepage_recognition_preview_image() -> FileResponse:
    response = public_asset(
        STATIC_DIR / "homepage-preview" / "crying-character.png",
        stable_loader=True,
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.get("/preview/homepage-mobile", include_in_schema=False)
@router.get("/preview/homepage-mobile/", include_in_schema=False)
def homepage_mobile_preview(embed: str | None = Query(default=None)) -> HTMLResponse:
    template = (STATIC_DIR / "homepage-preview" / "mobile.html").read_text(
        encoding="utf-8"
    )
    template = template.replace(
        "{{INTENSIVE_PUBLIC_CTA_DESTINATION}}",
        INTENSIVE_PUBLIC_CTA["destination"],
    ).replace(
        "{{INTENSIVE_PUBLIC_CTA_LABEL}}",
        INTENSIVE_PUBLIC_CTA["button_label"],
    )
    if embed == "tilda":
        template = template.replace(
            '<body data-page-theme="blue-mist">',
            '<body data-page-theme="blue-mist" data-tilda-homepage-embed="true">',
            1,
        ).replace(
            'data-pricing-endpoint="/api/pricing/site/preview"',
            'data-pricing-endpoint="/api/pricing/site"',
            1,
        ).replace(
            'data-checkout-endpoint="/api/pricing/site/preview-checkout"',
            'data-checkout-endpoint="/api/pricing/site/checkout"',
            1,
        )
    response = HTMLResponse(template, headers={"Cache-Control": "no-cache"})
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.get("/preview/direct-intensive", include_in_schema=False)
@router.get("/preview/direct-intensive/", include_in_schema=False)
def direct_intensive_preview() -> HTMLResponse:
    fragment = (
        STATIC_DIR / "homepage-preview" / "direct-intensive.html"
    ).read_text(encoding="utf-8")
    response = HTMLResponse(fragment, headers={"Cache-Control": "no-cache"})
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.get("/preview/direct-intensive/t123", include_in_schema=False)
def direct_intensive_t123_source() -> PlainTextResponse:
    fragment = (
        STATIC_DIR / "homepage-preview" / "direct-intensive.html"
    ).read_text(encoding="utf-8")
    response = PlainTextResponse(fragment, headers={"Cache-Control": "no-cache"})
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.get("/preview/homepage-reviews-wall", include_in_schema=False)
@router.get("/preview/homepage-reviews-wall/", include_in_schema=False)
def homepage_reviews_wall_preview() -> HTMLResponse:
    source = (STATIC_DIR / "homepage-preview" / "mobile.html").read_text(
        encoding="utf-8"
    )
    head = source[: source.index('<body data-page-theme="blue-mist">')]
    wall = homepage_library_fragment(source, "reviews-wall").replace(
        'href="#pricing"', 'href="/preview/homepage-mobile#pricing"'
    )
    template = head.replace(
        "<title>Новая главная — мобильная цепочка принятых блоков</title>",
        "<title>Отзывы — голосовые и скриншоты</title>",
        1,
    ) + (
        '<body data-page-theme="blue-mist" data-library-block="reviews-wall" '
        'data-library-status="accepted">\n'
        '<main class="homepage-chain">\n'
        f'{homepage_library_fragment(source, "reviews-voice")}\n'
        f'{homepage_library_fragment(source, "reviews-featured")}\n'
        f'{wall}\n'
        '</main>\n'
        f'{homepage_library_fragment(source, "reviews-lightbox")}\n'
        f'{homepage_library_fragment(source, "reviews-script")}\n'
        '</body>\n</html>\n'
    )
    response = HTMLResponse(template, headers={"Cache-Control": "no-cache"})
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.get("/preview/homepage-mobile/{asset_name}", include_in_schema=False)
def homepage_mobile_preview_asset(asset_name: str) -> FileResponse:
    if asset_name not in HOMEPAGE_MOBILE_PREVIEW_ASSETS:
        raise HTTPException(status_code=404, detail="preview asset not found")
    response = public_asset(
        STATIC_DIR / "homepage-preview" / asset_name,
        stable_loader=True,
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@router.get("/apps/{app_code}.html", include_in_schema=False)
def app_fragment(app_code: str) -> Response:
    if app_code not in {"account", "dqs", "strength", "metabolism", "recipes", "masterclass-course", "calories-course", "masterclass-sales", "onboarding-questionnaire", "masterclass-offers", "recipes-part-1", "recipes-part-2", "closing-review", "personal-access", "video-player"}:
        raise HTTPException(status_code=404, detail="app not found")
    if app_code == "masterclass-course":
        return public_asset(STATIC_DIR / "masterclass-first-days-preview.html")
    if app_code == "calories-course":
        template = (STATIC_DIR / "masterclass-first-days-preview.html").read_text(
            encoding="utf-8"
        )
        replacements = {
            "</head>": "<style>#calories-course-app .timer{display:none} #calories-course-app .unlock{justify-content:flex-end}</style></head>",
            "Мастер-класс · первые дни": "Калорийный курс",
            'id="masterclass-course-app"': 'id="calories-course-app"',
            "edabalans_first_days_v2": "edabalans_calories_course_v1",
            "/api/masterclass/course": "/api/calories/course",
            "/content/masterclass/course/course.json": "/content/calories/course/course.json",
            "masterclass-course": "calories-course",
            "course_day": "calories_stage",
            "course_material": "calories_material",
            "d.number===21": "d.number===days.length",
            "День ": "Этап ",
            "День пройден": "Этап пройден",
            "День уже открыт": "Этап уже открыт",
            "К материалам дня": "К материалам этапа",
            "Прошлый день": "Прошлый этап",
            "Задание на сегодня": "Задание этапа",
            "Следующий день": "Следующий этап",
            "следующий день": "следующий этап",
            "следующего дня": "следующего этапа",
            "Следующий этап откроется после выполнения задания и окончания таймера.": "Следующий этап откроется сразу после выполнения задания.",
            "До открытия следующего этапа осталось": "Следующий этап",
            "Черновик · требуется редактура": "Материал готовится",
            "Нужна редактура": "Материал готовится",
            "Авторский материал для этой карточки ещё не загружен.": "Текст будет опубликован здесь.",
            "['dqs','recipes-part-1','recipes-part-2','closing-review']": "['dqs','recipes-part-1','recipes-part-2','closing-review','metabolism']",
            "Следующий этап откроется утром": "Следующий этап откроется сразу",
            "<strong>06:00</strong><span>по вашему местному времени</span>": "<strong>Сразу</strong><span>после задания</span>",
            "Если завершить день до полуночи по вашему местному времени, продолжение откроется в ближайшие <strong>06:00</strong>. Если закончить после полуночи — в 06:00 уже через день. Точное время покажет таймер.": "После всех обязательных материалов и пунктов задания следующий этап можно открыть сразу.",
            "дню ": "этапу ",
            "Открыть день ": "Открыть этап ",
            "Перейти к дню ": "Перейти к этапу ",
            "Мастер-класс завершён": "Калорийный курс завершён",
            "Мастер-класса": "Калорийного курса",
            "Мастер-класс": "Калорийный курс",
            "masterclass-web": "calories-course-web",
            "edabalans:masterclass-event": "edabalans:calories-event",
            "EdabalansMasterclassEventSink": "EdabalansCaloriesEventSink",
            "Masterclass load failed": "Calories course load failed",
            "День": "Этап",
            "дня": "этапа",
            "день": "этап",
        }
        for source, target in replacements.items():
            template = template.replace(source, target)
        return HTMLResponse(
            template,
            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"},
        )
    if app_code == "video-player":
        return public_asset(
            STATIC_DIR / "video-player-development" / "player-standard-with-contents.html"
        )
    return public_asset(STATIC_DIR / "apps" / f"{app_code}.html")


@router.get("/apps/dqs-category-rules.js", include_in_schema=False)
def dqs_category_rules() -> FileResponse:
    return public_asset(STATIC_DIR / "apps" / "dqs-category-rules.js")


@router.get("/assets/{asset_name}", include_in_schema=False)
def app_asset(asset_name: str) -> FileResponse:
    if asset_name not in {"masterclass.js", "masterclass.css", "app-shell.css", "max-logo.png", "content-gallery.js"}:
        raise HTTPException(status_code=404, detail="asset not found")
    return public_asset(STATIC_DIR / asset_name)


@router.get("/legal/{document_code}.html", include_in_schema=False)
def legal_document(document_code: str) -> FileResponse:
    if document_code not in {"index", "disclaimer", "privacy", "consent", "messages", "offer"}:
        raise HTTPException(status_code=404, detail="legal document not found")
    return public_asset(STATIC_DIR / "legal" / f"{document_code}.html")


@router.get("/legal", include_in_schema=False)
@router.get("/legal/", include_in_schema=False)
def legal_index() -> FileResponse:
    return public_asset(STATIC_DIR / "legal" / "index.html")


@router.get("/legal/legal.css", include_in_schema=False)
def legal_stylesheet() -> FileResponse:
    return public_asset(STATIC_DIR / "legal" / "legal.css")


@router.get("/legal/{document_code}", include_in_schema=False)
def legal_document_friendly(document_code: str) -> FileResponse:
    if document_code not in {"disclaimer", "privacy", "consent", "messages", "offer"}:
        raise HTTPException(status_code=404, detail="legal document not found")
    return public_asset(STATIC_DIR / "legal" / f"{document_code}.html")


@router.get("/intensive/intensive.css", include_in_schema=False)
def intensive_stylesheet() -> FileResponse:
    return public_asset(STATIC_DIR / "intensive" / "intensive.css")


@router.get("/intensive/intensive.js", include_in_schema=False)
def intensive_script() -> FileResponse:
    return public_asset(STATIC_DIR / "intensive" / "intensive.js")


@router.get("/intensive/runtime.js", include_in_schema=False)
def intensive_runtime_script() -> FileResponse:
    return public_asset(STATIC_DIR / "intensive" / "runtime.js")


@router.get("/intensive/intensive-components.css", include_in_schema=False)
def intensive_components_stylesheet() -> FileResponse:
    return public_asset(STATIC_DIR / "intensive" / "intensive-components.css")


@router.get("/intensive/max-full-colored-official.png", include_in_schema=False)
def intensive_max_logo() -> FileResponse:
    return public_asset(STATIC_DIR / "intensive" / "max-full-colored-official.png")


@router.get("/intensive/assets/{day_code}/{asset_name}", include_in_schema=False)
def intensive_content_asset(day_code: str, asset_name: str) -> FileResponse:
    allowed = {
        "intensive-day-2": {
            "intro-cat.png",
            "product-categories.png",
            "alexandra-review.jpg",
        }
    }
    if asset_name not in allowed.get(day_code, set()):
        raise HTTPException(status_code=404, detail="intensive asset not found")
    return public_asset(STATIC_DIR / "intensive" / "assets" / day_code / asset_name)


@router.get("/intensive", include_in_schema=False)
@router.get("/intensive/", include_in_schema=False)
@router.get("/intensive/menu", include_in_schema=False)
def intensive_menu(
) -> FileResponse:
    response = public_asset(STATIC_DIR / "intensive" / "index.html")
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/intensive/start", include_in_schema=False)
def intensive_entry(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    identity = None
    supplied_token = request.query_params.get("i") or request.query_params.get("token")
    if supplied_token:
        token_row = access_token_row(db, supplied_token)
        if token_row is None:
            raise HTTPException(status_code=404, detail="intensive link not found")
        identity = (token_row.user_id, token_row.platform)
        record_entry_attribution(db, token_row.user_id, token_row.platform, request)
        db.commit()
    if identity is None:
        identity = session_identity(request, settings.app_auth_secret)
    if identity is not None and db.get(User, identity[0]) is None:
        identity = None
    if identity is None:
        return RedirectResponse(attributed_path(request, "/intensive"), status_code=307)
    user_id, platform = identity
    rows = progress_rows(db, user_id)
    target = "/intensive" if 4 in rows else f"/intensive/day-{current_day(rows)}"
    response = RedirectResponse(attributed_path(request, target), status_code=307)
    response.headers["Referrer-Policy"] = "no-referrer"
    set_session(response, request, settings.app_auth_secret, user_id, platform)
    return response


@router.get("/api/intensive/state")
def intensive_state(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    public_state = {
        "identified": False,
        "platform": None,
        "opened_days": [],
        "assignment_days": [],
        "current_day": 1,
        "unlocked_days": [1, 2, 3, 4],
        "unlock_at": {},
        "offer": None,
    }
    identity = session_identity(request, settings.app_auth_secret)
    if identity is None:
        return public_state
    user_id, platform = identity
    if db.get(User, user_id) is None:
        return public_state
    return state_payload(db, user_id, platform)


@router.get("/api/intensive/offer-token")
def intensive_offer_token(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    identity = session_identity(request, settings.app_auth_secret)
    if identity is None:
        raise HTTPException(status_code=401, detail="intensive identity required")
    user_id, _ = identity
    offer = offer_for_user(db, user_id)
    if offer is None or offer.status != "active" or not offer.expires_at:
        raise HTTPException(status_code=404, detail="intensive offer not found")
    expires_at = offer.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="intensive offer expired")
    token = create_offer_token(db, user_id, expires_at)
    db.commit()
    return {
        "ok": True,
        "offer_id": "intensive-day4-1000",
        "discount_amount": 1000,
        "expires_at": expires_at.isoformat(),
        "token": token,
    }


@router.post("/api/intensive/day-{day_number}/post/{messenger}")
def intensive_post_target(
    day_number: int,
    messenger: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if day_number not in range(1, 4) or messenger not in {"telegram", "max"}:
        raise HTTPException(status_code=404, detail="intensive post not found")
    identity = session_identity(request, settings.app_auth_secret)
    if identity is None:
        raise HTTPException(status_code=401, detail="intensive identity required")
    user_id, _ = identity
    rows = progress_rows(db, user_id)
    if not day_unlocked(rows, day_number):
        raise HTTPException(status_code=403, detail="intensive day is not open")
    targets = {
        # Final per-day Telegram/MAX publication URLs are inserted from the VSL
        # checkpoint before release. Generic channel roots must not masquerade as tasks.
    }
    target = targets.get((day_number, messenger))
    if not target:
        raise HTTPException(status_code=503, detail="intensive assignment is not published")
    if mark_assignment_opened(db, user_id, day_number, messenger) is None:
        raise HTTPException(status_code=409, detail="intensive day is not open")
    db.commit()
    return {"target_url": target}


def intensive_day_asset(
    day_code: str,
    request: Request,
    settings: Settings,
    db: Session,
) -> Response:
    if day_code not in {"day-1", "day-2", "day-3", "day-4"}:
        raise HTTPException(status_code=404, detail="intensive day not found")
    day_number = int(day_code[-1])
    identity = session_identity(request, settings.app_auth_secret)
    if identity is not None and db.get(User, identity[0]) is not None:
        user_id, _ = identity
        if open_day(db, user_id, day_number) is None:
            return RedirectResponse(attributed_path(request, "/intensive"), status_code=307)
        db.commit()
    response = public_asset(STATIC_DIR / "intensive" / f"{day_code}.html")
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/intensive/{day_code}.html", include_in_schema=False)
def intensive_day_html(
    day_code: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    return intensive_day_asset(day_code, request, settings, db)


@router.get("/intensive/{day_code}", include_in_schema=False)
def intensive_day_friendly(
    day_code: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    return intensive_day_asset(day_code, request, settings, db)


def error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def jsonp(payload: dict[str, Any], callback: str | None) -> Response:
    if callback and JSONP_CALLBACK.match(callback):
        body = f"{callback}({json.dumps(payload, ensure_ascii=False, separators=(',', ':'))});"
        return Response(body, media_type="application/javascript; charset=utf-8")
    return JSONResponse(payload)


def empty_strength_state(user_id: uuid.UUID) -> StrengthState:
    return StrengthState(
        user_id=user_id,
        workout_types=[
            {"workout_type": 1, "title": "Тренировка 1", "active": True, "sort_order": 1},
            {"workout_type": 2, "title": "Тренировка 2", "active": True, "sort_order": 2},
            {"workout_type": 3, "title": "Тренировка 3", "active": True, "sort_order": 3},
        ],
        hidden_exercises=[],
        workouts=[],
        source="app",
    )


APP_STATE_MODELS = {
    "dqs": DqsState,
    "strength": StrengthState,
    "metabolism": MetabolismState,
}


def app_resource_codes(app_code: str) -> tuple[str, ...]:
    if app_code == "metabolism":
        return ("metabolism", "ACCESS_CALORIES")
    return (app_code,)


def empty_app_state(app_code: str, user_id: uuid.UUID) -> Any:
    if app_code == "dqs":
        return DqsState(user_id=user_id, days={}, source="admin_open")
    if app_code == "strength":
        state = empty_strength_state(user_id)
        state.source = "admin_open"
        return state
    if app_code == "metabolism":
        return MetabolismState(user_id=user_id, variants={}, source="admin_open")
    raise HTTPException(status_code=404, detail="app not found")


@router.get("/api/apps/dqs")
def dqs_legacy_get(
    action: str = "ping",
    email: str = "",
    startDate: str = "",
    day: str = "",
    data: str = "",
    callback: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    try:
        if action == "ping":
            return jsonp({"ok": True, "service": "DQS", "dayCount": 30, "categoryCount": 17}, callback)
        user = resolve_user_for_resource(db, email, "dqs")
        state = db.scalar(select(DqsState).where(DqsState.user_id == user.id))
        if not state:
            state = DqsState(user_id=user.id, days={}, source="app")
            db.add(state)
            db.flush()

        if action == "openUser":
            event = db.scalar(select(MasterclassEvent).where(MasterclassEvent.user_id == user.id, MasterclassEvent.event_key == "dqs_opened"))
            if not event:
                event = MasterclassEvent(user_id=user.id, event_key="dqs_opened", event_type="dqs_opened", placement="dqs", details={})
                db.add(event); db.flush()
            days = [state.days.get(str(index)) for index in range(1, DAY_COUNT + 1)]
            payload = {
                "ok": True,
                "email": normalize_email(email),
                "startDate": state.start_date or "",
                "needsStartDate": not bool(state.start_date),
                "days": days,
                "version": state.version,
            }
        elif action == "completeTutorial":
            event = db.scalar(select(MasterclassEvent).where(
                MasterclassEvent.user_id == user.id,
                MasterclassEvent.event_key == "dqs_tutorial_completed",
            ))
            if not event:
                event = MasterclassEvent(
                    user_id=user.id,
                    event_key="dqs_tutorial_completed",
                    event_type="dqs_tutorial_completed",
                    placement="dqs",
                    details={},
                )
                db.add(event)
                db.flush()
            payload = {"ok": True, "completed": True}
        elif action == "setStartDate":
            date.fromisoformat(startDate)
            already = bool(state.start_date)
            if not already:
                state.start_date = startDate
                state.version += 1
            payload = {"ok": True, "startDate": state.start_date, "alreadySet": already, "version": state.version}
        elif action == "saveDay":
            day_number = int(day)
            if not 1 <= day_number <= DAY_COUNT:
                raise ValueError("INVALID_DAY")
            incoming = json.loads(data)
            portions = incoming.get("p")
            diversity = incoming.get("d")
            if not isinstance(portions, list) or len(portions) != CATEGORY_COUNT:
                raise ValueError("INVALID_PORTIONS")
            if not isinstance(diversity, list) or len(diversity) != CATEGORY_COUNT:
                raise ValueError("INVALID_DIVERSITY")
            normalized_portions = []
            for value in portions:
                number = float(value)
                if not math.isfinite(number) or number < 0 or abs(number * 2 - round(number * 2)) > 0.000001:
                    raise ValueError("PORTION_MUST_BE_HALF_STEP")
                normalized_portions.append(round(number * 2) / 2)
            if any(value not in (True, False, None) for value in diversity):
                raise ValueError("INVALID_DIVERSITY_VALUE")
            saved = {
                "v": 2,
                "updated": datetime.now(timezone.utc).isoformat(),
                "p": normalized_portions,
                "d": diversity,
            }
            next_days = dict(state.days or {})
            next_days[str(day_number)] = saved
            state.days = next_days
            state.version += 1
            payload = {"ok": True, "data": saved, "version": state.version}
        else:
            payload = error("UNKNOWN_ACTION")
        db.commit()
        return jsonp(payload, callback)
    except (AppAccessError, ValueError, TypeError, json.JSONDecodeError) as exc:
        db.rollback()
        return jsonp(error(str(exc)), callback)


@router.get("/api/apps/dqs/access")
def dqs_access_status(email: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Confirm DQS entitlement before the shared legal gate is displayed."""
    try:
        user = resolve_user_for_resource(
            db,
            email,
            "dqs",
            require_legal_acceptance=False,
        )
    except AppAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "ok": True,
        "legal": legal_status_payload(db, user.id),
    }


def strength_payload(db: Session, state: StrengthState, user_id: uuid.UUID, workout_type: int) -> dict[str, Any]:
    catalog = []
    settings = {
        (str(item.get("exercise_id")), int(item.get("workout_type", 0))): item
        for item in (state.hidden_exercises or [])
        if isinstance(item, dict)
    }
    exercises = db.scalars(
        select(StrengthExercise).where(StrengthExercise.active.is_(True)).order_by(StrengthExercise.sort_order, StrengthExercise.name)
    ).all()
    for exercise in exercises:
        allowed_types = exercise.metadata_json.get("workout_types", [1, 2, 3])
        if workout_type not in allowed_types:
            continue
        own = settings.get((exercise.code, workout_type), {})
        catalog.append({
            "user_id": str(user_id),
            "workout_type": workout_type,
            "exercise_id": exercise.code,
            "exercise_name": exercise.name,
            "active": own.get("active", True),
            "sort_order": own.get("sort_order", exercise.sort_order),
            "source": exercise.metadata_json.get("source", "catalog"),
        })
    catalog.sort(key=lambda item: int(item.get("sort_order") or 0))

    sessions, session_exercises, sets = [], [], []
    own_workouts = [w for w in (state.workouts or []) if int(w.get("workout_type", 0)) == workout_type]
    own_workouts.sort(key=lambda item: int(item.get("session_number") or 0))
    for workout in own_workouts:
        session_id = str(workout.get("session_id") or workout.get("id"))
        number = int(workout.get("session_number") or 0)
        sessions.append({
            "session_id": session_id, "user_id": str(user_id), "workout_type": workout_type,
            "session_number": number, "date": workout.get("date", ""), "status": workout.get("status", "planned"),
            "legacy_group": workout.get("legacy_group", ""), "source": workout.get("source", "app"),
            "created_at": workout.get("created_at", ""), "updated_at": workout.get("updated_at", ""),
        })
        for ex_index, exercise in enumerate(workout.get("exercises", []), 1):
            session_exercises.append({
                "session_id": session_id, "user_id": str(user_id), "workout_type": workout_type,
                "session_number": number, "exercise_id": exercise.get("exercise_id"),
                "exercise_name": exercise.get("exercise_name", ""),
                "sort_order": exercise.get("sort_order", ex_index), "note": exercise.get("note", ""),
                "source": exercise.get("source", "app"),
            })
            for set_index, item in enumerate(exercise.get("sets", []), 1):
                sets.append({
                    "session_id": session_id, "user_id": str(user_id), "workout_type": workout_type,
                    "session_number": number, "exercise_id": exercise.get("exercise_id"),
                    "exercise_name": exercise.get("exercise_name", ""), "set_number": item.get("set_number", set_index),
                    **{key: item.get(key, "") for key in (
                        "plan_weight", "plan_reps", "fact_weight", "fact_reps", "rpe",
                        "plan_weight_raw", "plan_reps_raw", "fact_weight_raw", "fact_reps_raw", "rpe_raw")},
                    "source": item.get("source", "app"),
                })
    types = [{"user_id": str(user_id), **item} for item in (state.workout_types or [])]
    return {"workout_types": types, "exercise_catalog": catalog, "sessions": sessions, "session_exercises": session_exercises, "sets": sets}


@router.api_route("/api/apps/strength", methods=["GET", "POST"])
async def strength_legacy(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        if request.method == "GET":
            body = dict(request.query_params)
        else:
            body = json.loads((await request.body()).decode("utf-8"))
        action = str(body.get("action") or "ping")
        if action == "ping":
            return JSONResponse({"ok": True, "service": "strength-training"})
        admin_username = None
        target_user_id = body.get("target_user_id")
        if target_user_id:
            admin_username = session_admin(request)
            if not admin_username:
                raise HTTPException(status_code=401, detail="admin authentication required")
            user = db.get(User, uuid.UUID(str(target_user_id)))
            if user is None or user.merged_into_user_id is not None:
                raise HTTPException(status_code=404, detail="user not found")
        else:
            user = resolve_user_for_resource(db, body.get("email"), "strength")
        state = db.scalar(select(StrengthState).where(StrengthState.user_id == user.id))
        if not state:
            if admin_username:
                raise HTTPException(status_code=404, detail="application state not found")
            state = empty_strength_state(user.id)
            db.add(state)
            db.flush()
        user_payload = {"user_id": str(user.id), "email": primary_email(db, user.id) if admin_username else normalize_email(body.get("email")), "display_name": user.display_name or "", "status": user.status}
        if action == "openUser":
            payload = {"ok": True, "user": user_payload}
        elif action == "getWorkout":
            payload = {"ok": True, "user": user_payload, "workout": strength_payload(db, state, user.id, int(body.get("type") or 1))}
        elif action == "saveSession":
            workout_type = int(body.get("workout_type") or 0)
            session = body.get("session") or {}
            workouts = list(state.workouts or [])
            own_numbers = [int(w.get("session_number") or 0) for w in workouts if int(w.get("workout_type") or 0) == workout_type]
            number = int(session.get("session_number") or 0) or (max(own_numbers, default=0) + 1)
            session_id = str(session.get("session_id") or f"{user.id}_t{workout_type}_s{number:02d}")
            now = datetime.now(timezone.utc).isoformat()
            item = {**session, "session_id": session_id, "workout_type": workout_type, "session_number": number, "updated_at": now, "created_at": session.get("created_at") or now, "source": "app"}
            item["status"] = "filled" if any(
                set_item.get("rpe") not in (None, "")
                for exercise in item.get("exercises", []) for set_item in exercise.get("sets", [])
            ) else "planned"
            workouts = [w for w in workouts if str(w.get("session_id")) != session_id]
            workouts.append(item)
            state.workouts = workouts
            state.version += 1
            payload = {"ok": True, "session": item, "version": state.version}
        elif action == "saveExerciseSettings":
            workout_type = int(body.get("workout_type") or 0)
            settings = [item for item in (state.hidden_exercises or []) if int(item.get("workout_type", 0)) != workout_type]
            settings.extend({**item, "workout_type": workout_type} for item in (body.get("exercises") or []))
            state.hidden_exercises = settings
            state.version += 1
            payload = {"ok": True, "version": state.version}
        elif action == "getStats":
            workout_type = int(body.get("type") or 1)
            exercise_id = str(body.get("exercise_id") or "")
            history = []
            for workout in sorted(state.workouts or [], key=lambda w: str(w.get("date") or "")):
                if int(workout.get("workout_type") or 0) != workout_type or not workout.get("date"):
                    continue
                exercise = next((x for x in workout.get("exercises", []) if str(x.get("exercise_id")) == exercise_id), None)
                candidates = []
                for set_item in (exercise or {}).get("sets", [])[1:]:
                    try:
                        weight, reps, rpe = float(set_item["fact_weight"]), float(set_item["fact_reps"]), float(set_item["rpe"])
                        estimate = weight * (1 + (reps + max(0, 10 - rpe)) / 30) / (1 + 8 / 30)
                        candidates.append((weight, estimate, set_item))
                    except (KeyError, TypeError, ValueError):
                        pass
                if candidates:
                    best = sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[0]
                    history.append({"session_id": workout.get("session_id"), "session_number": workout.get("session_number"), "date": workout.get("date"), "estimated_8rm": round(best[1], 2), "source_set": best[2].get("set_number"), "source_weight": best[0], "source_reps": best[2].get("fact_reps"), "source_rpe": best[2].get("rpe")})
            payload = {"ok": True, "user": user_payload, "stats": history}
        else:
            payload = error("Unknown action: " + action)
        if admin_username and action in {"saveSession", "saveExerciseSettings"} and payload.get("ok"):
            db.add(AdminAppEdit(
                admin_username=admin_username,
                target_user_id=user.id,
                app_code="strength",
                action=action,
                details={"version_after": state.version},
            ))
        db.commit()
        return JSONResponse(payload)
    except (AppAccessError, ValueError, TypeError, json.JSONDecodeError) as exc:
        db.rollback()
        return JSONResponse(error(str(exc)))


@router.get("/api/apps/metabolism")
def metabolism_get(email: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        user = resolve_user_for_resource(db, email, ("metabolism", "ACCESS_CALORIES"))
        state = db.scalar(select(MetabolismState).where(MetabolismState.user_id == user.id))
        if not state:
            state = MetabolismState(user_id=user.id, variants={}, source="app")
            db.add(state)
            db.commit()
            db.refresh(state)
        return {"ok": True, "email": normalize_email(email), "variants": state.variants, "activeVariant": state.active_variant, "version": state.version}
    except AppAccessError as exc:
        return error(str(exc))


@router.put("/api/apps/metabolism")
async def metabolism_put(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        body = await request.json()
        user = resolve_user_for_resource(
            db, body.get("email"), ("metabolism", "ACCESS_CALORIES")
        )
        state = db.scalar(select(MetabolismState).where(MetabolismState.user_id == user.id))
        if not state:
            state = MetabolismState(user_id=user.id, variants={}, source="app")
            db.add(state)
            db.flush()
        apply_metabolism_update(state, body)
        db.commit()
        return JSONResponse({"ok": True, "version": state.version})
    except (AppAccessError, ValueError, TypeError) as exc:
        db.rollback()
        return JSONResponse(error(str(exc)), status_code=400)


def apply_metabolism_update(state: MetabolismState, body: dict[str, Any]) -> None:
    expected = body.get("version")
    if expected is not None and int(expected) != state.version:
        raise HTTPException(status_code=409, detail="STATE_VERSION_CONFLICT")
    variants = body.get("variants")
    active = int(body.get("activeVariant") or 1)
    if not isinstance(variants, dict) or active not in (1, 2):
        raise ValueError("INVALID_STATE")
    state.variants = variants
    state.active_variant = active
    state.version += 1


@router.get("/admin/api/apps/metabolism/users/{user_id}/runtime")
def admin_metabolism_get(
    user_id: uuid.UUID,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    state = db.scalar(select(MetabolismState).where(MetabolismState.user_id == user_id))
    if state is None:
        raise HTTPException(status_code=404, detail="application state not found")
    return {
        "ok": True,
        "variants": state.variants,
        "activeVariant": state.active_variant,
        "version": state.version,
    }


@router.put("/admin/api/apps/metabolism/users/{user_id}/runtime")
async def admin_metabolism_put(
    user_id: uuid.UUID,
    request: Request,
    admin_username: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> JSONResponse:
    state = db.scalar(select(MetabolismState).where(MetabolismState.user_id == user_id))
    if state is None:
        raise HTTPException(status_code=404, detail="application state not found")
    body = await request.json()
    version_before = state.version
    try:
        apply_metabolism_update(state, body)
        db.add(AdminAppEdit(
            admin_username=admin_username,
            target_user_id=user_id,
            app_code="metabolism",
            action="save_state",
            details={
                "changed_fields": ["variants", "active_variant"],
                "version_before": version_before,
                "version_after": state.version,
            },
        ))
        db.commit()
        return JSONResponse({"ok": True, "version": state.version})
    except HTTPException:
        db.rollback()
        raise
    except (ValueError, TypeError) as exc:
        db.rollback()
        return JSONResponse(error(str(exc)), status_code=400)


@router.get("/admin/api/apps/users")
def admin_app_users(
    app_code: str = Query(pattern="^(dqs|strength|metabolism)$"),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    model = APP_STATE_MODELS[app_code]
    states = db.scalars(select(model).order_by(model.updated_at.desc())).all()
    state_by_user = {item.user_id: item for item in states}
    now = datetime.now(timezone.utc)
    access_user_ids = set(
        db.scalars(
            select(UserAccess.user_id)
            .join(Resource, Resource.id == UserAccess.resource_id)
            .join(User, User.id == UserAccess.user_id)
            .where(
                Resource.code.in_(app_resource_codes(app_code)),
                Resource.status == "active",
                User.status == "active",
                User.merged_into_user_id.is_(None),
                UserAccess.revoked_at.is_(None),
                (UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now)),
            )
        ).all()
    )
    user_ids = set(state_by_user) | access_user_ids
    users = {
        item.id: item
        for item in db.scalars(
            select(User)
            .where(User.id.in_(user_ids), User.merged_into_user_id.is_(None))
            .order_by(User.display_name, User.created_at)
        ).all()
    } if user_ids else {}
    return {
        "ok": True,
        "users": [
            {
                "user_id": str(user_id),
                "display_name": users[user_id].display_name,
                "email": primary_email(db, user_id),
                "has_access": user_id in access_user_ids,
                "has_state": user_id in state_by_user,
                "version": state_by_user[user_id].version if user_id in state_by_user else None,
                "updated_at": utc_iso(state_by_user[user_id].updated_at) if user_id in state_by_user else "",
                "summary": admin_state_summary(app_code, state_by_user[user_id]) if user_id in state_by_user else {},
            }
            for user_id in users
        ],
    }


def admin_state_summary(app_code: str, state: Any) -> dict[str, Any]:
    if app_code == "dqs":
        days = state.days if isinstance(state.days, dict) else {}
        return {
            "start_date": state.start_date,
            "filled_days": sum(value not in (None, "", {}) for value in days.values()),
            "total_days": 30,
        }
    if app_code == "strength":
        workouts = state.workouts if isinstance(state.workouts, list) else []
        dates = [str(item.get("date")) for item in workouts if isinstance(item, dict) and item.get("date")]
        return {
            "sessions": len(workouts),
            "filled_sessions": sum(isinstance(item, dict) and item.get("status") == "filled" for item in workouts),
            "last_date": max(dates, default=None),
            "hidden_exercises": len(state.hidden_exercises if isinstance(state.hidden_exercises, list) else []),
        }
    variants = state.variants if isinstance(state.variants, dict) else {}
    return {
        "saved_variants": sum(value not in (None, "", {}) for value in variants.values()),
        "active_variant": state.active_variant,
        "formula_version": state.formula_version,
    }


def active_resource_codes(db: Session, user_id: uuid.UUID) -> set[str]:
    now = datetime.now(timezone.utc)
    return set(
        db.scalars(
            select(Resource.code)
            .join(UserAccess, UserAccess.resource_id == Resource.id)
            .where(
                UserAccess.user_id == user_id,
                UserAccess.revoked_at.is_(None),
                (UserAccess.expires_at.is_(None) | (UserAccess.expires_at > now)),
            )
        ).all()
    )


@router.get("/admin/api/users/{user_id}/modules")
def admin_user_modules(
    user_id: uuid.UUID,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user = db.get(User, user_id)
    if user is None or user.merged_into_user_id is not None:
        raise HTTPException(status_code=404, detail="user not found")
    access_codes = active_resource_codes(db, user_id)
    result: dict[str, Any] = {}
    for code, model in {"dqs": DqsState, "strength": StrengthState, "metabolism": MetabolismState}.items():
        state = db.scalar(select(model).where(model.user_id == user_id))
        result[code] = {
            "exists": state is not None,
            "has_access": bool(access_codes.intersection(app_resource_codes(code))),
            "updated_at": utc_iso(state.updated_at) if state else "",
            "version": state.version if state else None,
            "summary": admin_state_summary(code, state) if state else {},
        }
    telegram = db.scalar(
        select(MessengerAccount).where(
            MessengerAccount.user_id == user_id,
            MessengerAccount.platform == "telegram",
        ).limit(1)
    )
    result["telegram"] = {
        "exists": telegram is not None,
        "username": telegram.username if telegram else None,
        "last_seen_at": utc_iso(telegram.last_seen_at) if telegram else "",
    }
    return {"ok": True, "user_id": str(user_id), "modules": result}


@router.get("/admin/api/apps/{app_code}/users/{user_id}")
def admin_app_user(
    app_code: str,
    user_id: uuid.UUID,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    model = APP_STATE_MODELS.get(app_code)
    if model is None:
        raise HTTPException(status_code=404, detail="app not found")
    user = db.get(User, user_id)
    state = db.scalar(select(model).where(model.user_id == user_id))
    if user is None or user.merged_into_user_id is not None:
        raise HTTPException(status_code=404, detail="user not found")
    has_access = bool(
        active_resource_codes(db, user_id).intersection(app_resource_codes(app_code))
    )
    return {
        "ok": True,
        "app_code": app_code,
        "user": {
            "id": str(user.id),
            "display_name": user.display_name,
            "email": primary_email(db, user.id),
        },
        "has_access": has_access,
        "has_state": state is not None,
        "state": {
            "version": state.version,
            "updated_at": utc_iso(state.updated_at),
            "source": state.source,
            "summary": admin_state_summary(app_code, state),
            "data": admin_state_data(app_code, state),
        } if state else None,
    }


def admin_state_data(app_code: str, state: Any) -> dict[str, Any]:
    if app_code == "dqs":
        return {"start_date": state.start_date, "days": state.days}
    if app_code == "strength":
        return {
            "workout_types": state.workout_types,
            "hidden_exercises": state.hidden_exercises,
            "workouts": state.workouts,
        }
    return {
        "variants": state.variants,
        "active_variant": state.active_variant,
        "formula_version": state.formula_version,
    }


@router.post("/admin/api/apps/{app_code}/users/{user_id}/open")
def admin_open_app_user(
    app_code: str,
    user_id: uuid.UUID,
    admin_username: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    model = APP_STATE_MODELS.get(app_code)
    if model is None:
        raise HTTPException(status_code=404, detail="app not found")
    user = db.get(User, user_id)
    if user is None or user.merged_into_user_id is not None:
        raise HTTPException(status_code=404, detail="user not found")
    if app_code not in active_resource_codes(db, user_id):
        raise HTTPException(status_code=403, detail="user has no active access")
    state = db.scalar(select(model).where(model.user_id == user_id))
    created = state is None
    if created:
        state = empty_app_state(app_code, user_id)
        db.add(state)
        db.flush()
        db.add(
            AdminAppEdit(
                admin_username=admin_username,
                target_user_id=user_id,
                app_code=app_code,
                action="open_empty_state",
                details={"created": True, "version": state.version},
            )
        )
        db.commit()
        db.refresh(state)
    return {
        "ok": True,
        "created": created,
        "app_code": app_code,
        "user_id": str(user_id),
        "version": state.version,
    }
