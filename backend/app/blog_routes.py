from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


router = APIRouter()
BLOG_DIR = Path(__file__).resolve().parent / "static" / "blog"
BLOG_FONT_FILES = {"inter-cyrillic.woff2", "inter-latin.woff2"}


@router.get("/blog", include_in_schema=False)
@router.get("/blog/", include_in_schema=False)
def blog_home() -> FileResponse:
    response = FileResponse(BLOG_DIR / "index.html")
    response.headers["Cache-Control"] = "no-cache"
    return response


@router.get("/blog/fonts/{font_name}", include_in_schema=False)
def blog_font(font_name: str) -> FileResponse:
    if font_name not in BLOG_FONT_FILES:
        raise HTTPException(status_code=404, detail="font not found")
    response = FileResponse(BLOG_DIR / "fonts" / font_name, media_type="font/woff2")
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
