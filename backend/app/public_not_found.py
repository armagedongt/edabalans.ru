from pathlib import Path
from html import escape

from fastapi import APIRouter, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, HTMLResponse
from starlette.exceptions import HTTPException

from app.intensive_public_cta import INTENSIVE_PUBLIC_CTA


router = APIRouter(tags=["public-site"])
ASSET_DIR = Path(__file__).parent / "static" / "public-site-errors"
ORIGIN = "https://edabalans.ru"
HEADERS = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"}


def fragment() -> str:
    return (ASSET_DIR / "404-fragment.html").read_text(encoding="utf-8").replace(
        "{{intensive_url}}", escape(INTENSIVE_PUBLIC_CTA["destination"], quote=True)
    ).replace("{{origin}}", ORIGIN)


def page() -> str:
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        '<title>Страница не найдена — 404</title></head><body style="margin:0">'
        + fragment()
        + f'<script src="{ORIGIN}/site-header.js" defer></script>'
        f'<script src="{ORIGIN}/site-footer.js" defer></script></body></html>'
    )


def browser_navigation(request: Request) -> bool:
    path = request.url.path
    if request.method not in {"GET", "HEAD"}:
        return False
    if path.startswith(("/api", "/admin", "/mcp", "/assets/", "/intensive/assets/", "/public-site-assets/", "/public-site-errors/", "/blog/assets/", "/blog/fonts/", "/blog/media/", "/media/", "/preview/", "/integrations/", "/bot", "/telegram/", "/sherbakova/")):
        return False
    if Path(path).suffix and Path(path).suffix.lower() not in {".html", ".htm"}:
        return False
    for item in request.headers.get("accept", "").lower().split(","):
        parts = [part.strip() for part in item.split(";")]
        if parts[0] == "text/html":
            for parameter in parts[1:]:
                if parameter.startswith("q="):
                    try:
                        return float(parameter[2:]) > 0
                    except ValueError:
                        return False
            return True
    return False


async def public_http_exception(request: Request, exc: HTTPException):
    if exc.status_code == 404 and browser_navigation(request):
        return HTMLResponse(page(), status_code=404, headers=HEADERS)
    return await http_exception_handler(request, exc)


@router.get("/public-site-errors/404-fragment.html", include_in_schema=False)
def not_found_fragment():
    return HTMLResponse(fragment(), headers={**HEADERS, "Access-Control-Allow-Origin": "*"})


@router.get("/public-site-errors/404.js", include_in_schema=False)
def not_found_loader():
    return FileResponse(ASSET_DIR / "404.js", media_type="application/javascript", headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"})


@router.get("/public-site-errors/shrug-character-v1.svg", include_in_schema=False)
def not_found_illustration():
    return FileResponse(ASSET_DIR / "shrug-character-v1.svg", media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400", "Access-Control-Allow-Origin": "*"})
