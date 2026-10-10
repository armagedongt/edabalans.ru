"""Immutable, material-scoped raster attachments in the existing document store."""
from __future__ import annotations

import base64
import hashlib
import re

from fastapi import HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.managed_documents import active_document, document_hash
from app.models import ManagedDocumentVersion

DOCUMENT_TYPE = "editorial-image"
ORIGIN = "https://edabalans.ru"
NAME = re.compile(r"([a-f0-9]{64})\.(png|jpg|webp)")
SCOPE = re.compile(r"homepage|intensive|public:(?:program|recipes|consultation|calories|training)|blog:[a-z0-9-]+|course:(?:masterclass-21|calories):[a-z0-9-]+")


def scope_token(scope: str) -> str:
    if len(scope) > 160 or not SCOPE.fullmatch(scope):
        raise HTTPException(422, "Неизвестный материал картинки")
    return base64.urlsafe_b64encode(scope.encode()).decode().rstrip("=")


def image_url(scope: str, name: str) -> str:
    if not NAME.fullmatch(name):
        raise HTTPException(422, "Некорректное имя картинки")
    return f"{ORIGIN}/editorial-media/{scope_token(scope)}/{name}"


def image_key(scope: str, name: str) -> str:
    return hashlib.sha256(scope.encode()).hexdigest() + ":" + name


def current_source(db: Session, scope: str, *, request: Request | None = None):
    """Public readers check the deployed original; course readers reuse material authorization."""
    scope_token(scope)
    if scope == "intensive":
        from app.intensive_onepage import SOURCE
        return SOURCE.read_text(encoding="utf-8")
    if scope == "homepage":
        from app.homepage_content_service import active_homepage
        return active_homepage(db).payload
    if scope.startswith("public:"):
        from app.public_site_content_service import active_public_site_document
        return active_public_site_document(db, scope.split(":", 1)[1]).payload
    if scope.startswith("blog:"):
        from app.blog_draft_service import active_article, effective_article_payload, public_payload
        slug = scope.split(":", 1)[1]
        if request is None:
            return effective_article_payload(active_article(db, slug))
        return public_payload(db, slug) or {}
    _, course, step = scope.split(":", 2)
    if request is None:
        if course == "calories":
            from app.calorie_course_material_service import get_material
        else:
            from app.course_material_service import get_material
        return get_material(db, step)
    if course == "calories":
        from app.calorie_course_routes import course_materials
        return course_materials(email="", request=request, step_id=step, db=db)
    from app.masterclass_routes import course_materials
    from app.config import get_settings
    try:
        source = course_materials(email="", request=request, step_id=step, db=db, settings=get_settings())
    except HTTPException as exc:
        if exc.status_code not in {403, 404}:
            raise
        source = None
    if source and source.get("materials"):
        return source
    # The standalone recipe course serves the same originals without MK access.
    from app.recipe_course_routes import material
    try:
        return material(request=request, step_id=step, db=db)
    except HTTPException as exc:
        if source is None or exc.status_code not in {403, 404}:
            raise
        return source


def references(source, url: str) -> bool:
    if isinstance(source, str):
        # Only an image source, never an incidental quoted URL in authoring metadata.
        return bool(re.search(r"(?:\]\(|\bsrc=[\"'])" + re.escape(url) + r"(?=[\s)\"'])", source))
    if isinstance(source, dict):
        if isinstance(source.get("materials"), dict):
            return any(references(value, url) for value in source["materials"].values())
        return any(references(value, url) for key, value in source.items() if key in {
            "markdown", "source_content", "html", "materials", "material", "body", "text_content",
        })
    if isinstance(source, list):
        return any(references(value, url) for value in source)
    return False


def ingest(db: Session, *, scope: str, source: dict, admin: str) -> dict:
    current_source(db, scope)
    from app.blog_draft_service import _decode_media
    item, _ = _decode_media(source)
    if item["name"] != f"{item['sha256']}.{item['name'].rsplit('.', 1)[1]}":
        raise HTTPException(422, "Имя картинки должно содержать hash её байтов")
    key = image_key(scope, item["name"])
    existing = active_document(db, DOCUMENT_TYPE, key)
    if existing is None:
        payload = {**item, "scope": scope}
        db.add(ManagedDocumentVersion(document_type=DOCUMENT_TYPE, document_key=key,
            schema_version=1, version_no=1, payload=payload, content_hash=document_hash(payload),
            created_by=admin, is_active=True))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if active_document(db, DOCUMENT_TYPE, key) is None:
                raise
    return {"url": image_url(scope, item["name"]), "sha256": item["sha256"]}


def stored_image(db: Session, scope: str, name: str) -> dict:
    image_url(scope, name)
    version = active_document(db, DOCUMENT_TYPE, image_key(scope, name))
    if version is None or version.payload.get("scope") != scope:
        raise HTTPException(404, "Картинка не найдена")
    return version.payload


def stored_bytes(db: Session, scope: str, name: str) -> tuple[bytes, str]:
    item = stored_image(db, scope, name)
    raw = base64.b64decode(item["content_base64"], validate=True)
    if hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise HTTPException(503, "Нарушена целостность картинки")
    return raw, item["mime"]


def markdown_media(db: Session, scope: str, markdown: str) -> list[dict]:
    """Only stored attachments for this article may join its publication contract."""
    urls = re.findall(r"!\[[^\]]*\]\(([^\s)]+)", markdown)
    urls = [url for url in urls if "/editorial-media/" in url]
    if not urls:
        return []
    prefix = f"{ORIGIN}/editorial-media/{scope_token(scope)}/"
    result = []
    total = 0
    for url in dict.fromkeys(urls):
        if not url.startswith(prefix):
            raise HTTPException(422, "Картинка принадлежит другому материалу")
        name = url.removeprefix(prefix)
        item = stored_image(db, scope, name)
        total += len(base64.b64decode(item["content_base64"], validate=True))
        result.append({key: item[key] for key in ("name", "sha256", "mime", "provenance", "alt", "width", "height")}
                      | {"storage": "editorial", "url": url})
    if len(result) > 8 or total > 4 * 1024 * 1024:
        raise HTTPException(422, "В материале допускается до восьми новых картинок и 4 MiB")
    return result


def decode_scope(token: str) -> str:
    if len(token) > 220 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise HTTPException(404, "Картинка не найдена")
    try:
        scope = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
        if scope_token(scope) != token:
            raise ValueError()
    except (ValueError, UnicodeError, HTTPException):
        raise HTTPException(404, "Картинка не найдена")
    return scope


def delivered_bytes(db: Session, *, token: str, name: str, request: Request) -> tuple[bytes, str]:
    scope = decode_scope(token)
    stored_image(db, scope, name)
    source = current_source(db, scope, request=request)
    if not references(source, image_url(scope, name)):
        raise HTTPException(404, "Картинка не опубликована в материале")
    return stored_bytes(db, scope, name)
