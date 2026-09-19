from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth import admin_identity, security
from app.blog_content import toc_html
from app.blog_draft_service import (
    active_article,
    active_articles,
    article_versions,
    media_bytes,
    render_article,
    save_package,
    serialize_article,
    update_text,
)
from app.database import get_db


BLOG_DIR = Path(__file__).resolve().parent / "static" / "blog"
PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
}
BLOG_DRAFT_BODY_LIMIT = 8 * 1024 * 1024


class BlogDraftBodyLimitMiddleware:
    def __init__(self, app, max_body_size: int = BLOG_DRAFT_BODY_LIMIT):
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        method = scope.get("method", "")
        protected = method in {"PUT", "PATCH", "POST"} and path.startswith(
            "/admin/api/blog/articles/"
        )
        if not protected:
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        credentials = await security(request)
        if not admin_identity(request, credentials):
            response = JSONResponse(
                {"detail": "admin authentication required"},
                status_code=401,
                headers={
                    **PRIVATE_HEADERS,
                    "WWW-Authenticate": 'Basic realm="Edabalans Blog"',
                },
            )
            await response(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = self.max_body_size + 1
            if declared < 0 or declared > self.max_body_size:
                await self._reject(scope, receive, send)
                return
        received = 0
        messages = []
        while True:
            message = await receive()
            messages.append(message)
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_size:
                    await self._reject(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                return
        position = 0

        async def replay_receive():
            nonlocal position
            if position < len(messages):
                message = messages[position]
                position += 1
                return message
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(scope, receive, send):
        response = JSONResponse(
            {"detail": "Пакет статьи превышает 8 MiB"},
            status_code=413,
            headers=PRIVATE_HEADERS,
        )
        await response(scope, receive, send)


def private_response(response: Response) -> None:
    response.headers.update(PRIVATE_HEADERS)


router = APIRouter(
    tags=["blog-authoring"], dependencies=[Depends(private_response)]
)


class DraftMedia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=5, max_length=100)
    content_base64: str = Field(min_length=1, max_length=1_500_000)
    provenance: str = Field(min_length=1, max_length=2000)
    alt: str = Field(default="", max_length=500)


class DraftPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=200)
    excerpt: str = Field(default="", max_length=500)
    category: str
    markdown: str = Field(min_length=1, max_length=250_000)
    visibility: Literal["public", "internal"] = "public"
    editorial_status: Literal["moderation"] = "moderation"
    cta: str
    sources: list[str] = Field(min_length=1, max_length=20)
    source_id: str | None = Field(default=None, max_length=160)
    hero: str | None = Field(default=None, max_length=100)
    media: list[DraftMedia] = Field(default_factory=list, max_length=8)
    metadata: dict = Field(default_factory=dict)


class DraftTextUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    markdown: str = Field(min_length=1, max_length=250_000)


class DraftPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    markdown: str | None = Field(default=None, min_length=1, max_length=250_000)


def optional_blog_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str | None:
    return admin_identity(request, credentials)


def require_blog_admin(identity: str | None = Depends(optional_blog_admin)) -> str:
    if not identity:
        raise HTTPException(
            401,
            "admin authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Edabalans Blog"'},
        )
    return identity


def require_blog_mutation(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str:
    identity = admin_identity(request, credentials)
    if not identity:
        raise HTTPException(
            401,
            "admin authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Edabalans Blog"'},
        )
    authorization = request.headers.get("authorization", "")
    if authorization.casefold().startswith("basic "):
        return identity
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(403, "Для сохранения из браузера нужен same-origin запрос")
    parsed = urlsplit(origin)
    if parsed.scheme != request.url.scheme or parsed.netloc.casefold() != request.url.netloc.casefold():
        raise HTTPException(403, "Cross-origin изменение материала запрещено")
    return identity


@router.get("/admin/api/blog/articles")
def draft_index(
    _: str = Depends(require_blog_admin), db: Session = Depends(get_db)
) -> dict:
    return {
        "ok": True,
        "articles": [serialize_article(item, source=False) for item in active_articles(db)],
    }


@router.get("/admin/api/blog/articles/{slug}")
def draft_source(
    slug: str, _: str = Depends(require_blog_admin), db: Session = Depends(get_db)
) -> dict:
    article = active_article(db, slug)
    return {
        "ok": True,
        "article": serialize_article(article, source=True),
        "history": [
            {
                "version": item.version_no,
                "updated_at": item.created_at.isoformat(),
                "updated_by": item.created_by,
                "active": item.is_active,
            }
            for item in article_versions(db, slug)
        ],
    }


@router.put("/admin/api/blog/articles/{slug}")
def put_draft(
    slug: str,
    body: DraftPackage,
    admin: str = Depends(require_blog_mutation),
    db: Session = Depends(get_db),
) -> dict:
    source = body.model_dump(exclude={"expected_version"})
    article = save_package(
        db,
        slug=slug,
        source=source,
        expected_version=body.expected_version,
        admin=admin,
    )
    return {"ok": True, "article": serialize_article(article, source=False)}


@router.patch("/admin/api/blog/articles/{slug}/text")
def patch_draft_text(
    slug: str,
    body: DraftTextUpdate,
    admin: str = Depends(require_blog_mutation),
    db: Session = Depends(get_db),
) -> dict:
    article = update_text(
        db,
        slug=slug,
        markdown=body.markdown,
        expected_version=body.expected_version,
        admin=admin,
    )
    return {"ok": True, "article": serialize_article(article, source=True)}


@router.post("/admin/api/blog/articles/{slug}/preview")
def preview_draft(
    slug: str,
    body: DraftPreview,
    _: str = Depends(require_blog_admin),
    db: Session = Depends(get_db),
) -> dict:
    article = active_article(db, slug)
    html, toc = render_article(slug, article.payload, body.markdown)
    return {
        "ok": True,
        "html": html,
        "toc": [{"anchor": anchor, "title": title} for anchor, title in toc],
    }


def _not_found_without_disclosure() -> HTTPException:
    return HTTPException(404, "Материал не найден")


def _owner_article(
    slug: str, identity: str | None, db: Session
):
    if not identity:
        raise _not_found_without_disclosure()
    return active_article(db, slug)


@router.get("/blog/drafts/{slug}", include_in_schema=False)
def draft_page(
    slug: str,
    identity: str | None = Depends(optional_blog_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    article = _owner_article(slug, identity, db)
    payload = article.payload
    body, toc = render_article(slug, payload)
    hero = ""
    hero_url = (
        f"/blog/drafts/{escape(slug, quote=True)}/media/"
        f"{escape(payload['hero'], quote=True)}"
        if payload.get("hero")
        else ""
    )
    if payload.get("hero") and f'<img src="{hero_url}"' not in body:
        hero_name = escape(payload["hero"], quote=True)
        hero = (
            f'<figure><img src="{hero_url}" '
            f'alt="" loading="eager" decoding="async"></figure>'
        )
    replacements = {
        "{{TITLE}}": escape(payload["title"]),
        "{{CATEGORY}}": escape(payload["category"]),
        "{{VERSION}}": str(article.version_no),
        "{{VISIBILITY}}": "Служебная" if payload["visibility"] == "internal" else "Публичная",
        "{{STATUS}}": "На модерации",
        "{{HERO}}": hero,
        "{{ARTICLE_BODY}}": body,
        "{{TOC_DESKTOP}}": toc_html(toc, mobile=False),
        "{{TOC_MOBILE}}": toc_html(toc, mobile=True),
        "{{SLUG}}": escape(slug, quote=True),
    }
    rendered = (BLOG_DIR / "draft.html").read_text(encoding="utf-8")
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)
    return HTMLResponse(rendered, headers=PRIVATE_HEADERS)


@router.get("/blog/drafts/{slug}/edit", include_in_schema=False)
def draft_editor(
    slug: str,
    identity: str | None = Depends(optional_blog_admin),
    db: Session = Depends(get_db),
) -> FileResponse:
    _owner_article(slug, identity, db)
    return FileResponse(BLOG_DIR / "draft-editor.html", headers=PRIVATE_HEADERS)


@router.get("/blog/drafts/{slug}/media/{name}", include_in_schema=False)
def draft_media(
    slug: str,
    name: str,
    identity: str | None = Depends(optional_blog_admin),
    db: Session = Depends(get_db),
) -> Response:
    article = _owner_article(slug, identity, db)
    raw, mime, digest = media_bytes(article, name)
    return Response(
        raw,
        media_type=mime,
        headers={**PRIVATE_HEADERS, "ETag": f'"{digest}"'},
    )


def owner_cards_html(db: Session) -> str:
    cards = []
    for article in active_articles(db):
        item = article.payload
        visibility = item["visibility"]
        status = item["editorial_status"]
        cards.append(
            '<article class="owner-card" '
            f'data-owner-visibility="{escape(visibility, quote=True)}" '
            f'data-owner-status="{escape(status, quote=True)}">'
            f'<span class="card-tag">{escape(item["category"])}</span>'
            f'<h3>{escape(item["title"])}</h3>'
            f'<p>{"Служебная" if visibility == "internal" else "Публичная"} · '
            f'На модерации · версия {article.version_no}</p>'
            '<div class="owner-card-actions">'
            f'<a href="/blog/drafts/{escape(article.document_key, quote=True)}">Открыть</a>'
            f'<a href="/blog/drafts/{escape(article.document_key, quote=True)}/edit">Редактировать</a>'
            '</div></article>'
        )
    return (
        '<section class="shell owner-panel" aria-labelledby="owner-title">'
        '<div class="owner-panel-head"><div><p class="eyebrow">Видно только вам</p>'
        '<h2 id="owner-title">Редакция блога</h2></div>'
        '<a class="owner-api-link" href="/admin/api/blog/articles">API материалов</a></div>'
        '<div class="owner-filters" aria-label="Фильтры редакции">'
        '<button class="active" type="button" data-owner-filter="all" aria-pressed="true">Все</button>'
        '<button type="button" data-owner-filter="public" aria-pressed="false">Публичные</button>'
        '<button type="button" data-owner-filter="internal" aria-pressed="false">Служебные</button>'
        '<button type="button" data-owner-filter="moderation" aria-pressed="false">На модерации</button></div>'
        '<div class="owner-grid">' + "".join(cards) + '</div>'
        '<p class="owner-empty" hidden>В этом разделе материалов пока нет.</p></section>'
    )
