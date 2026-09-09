from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter()
BRAND_DIR = Path(__file__).resolve().parent / "static" / "brand"
BRAND_CACHE_HEADERS = {"Cache-Control": "public, max-age=3600"}


@router.get("/favicon.ico", include_in_schema=False)
def favicon_ico() -> FileResponse:
    return FileResponse(
        BRAND_DIR / "favicon.ico",
        media_type="image/vnd.microsoft.icon",
        headers=BRAND_CACHE_HEADERS,
    )


@router.get("/favicon.png", include_in_schema=False)
def favicon_png() -> FileResponse:
    return FileResponse(
        BRAND_DIR / "favicon.png",
        media_type="image/png",
        headers=BRAND_CACHE_HEADERS,
    )


@router.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon() -> FileResponse:
    return FileResponse(
        BRAND_DIR / "apple-touch-icon.png",
        media_type="image/png",
        headers=BRAND_CACHE_HEADERS,
    )
