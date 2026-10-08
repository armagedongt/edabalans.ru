"""Publish recipe prose while retaining its approved cards and exact source."""
from __future__ import annotations

import hashlib
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.course_material_service import (
    MAX_MATERIAL_BYTES, get_material, latest_version, material_item,
    publish_material, render_material,
)
from app.models import ContentItemVersion
from app.recipe_originals import METADATA_KEY, STEP_PREFIX, validated_cards
from scripts.publish_recipe_originals import publish as publish_originals


def source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def retained_source(version: ContentItemVersion | None) -> str | None:
    for block in (version.blocks or []) if version else []:
        if block.get("type") == "editorial_source" and block.get("format") == "markdown":
            return block["content"]
    return None


def authoring_status(db: Session, step_id: str) -> dict:
    item = material_item(db, step_id)
    version = latest_version(db, item)
    metadata = (item.metadata_json or {}).get(METADATA_KEY, {}) if item else {}
    content = retained_source(version)
    synchronized = bool(version and metadata.get("version") == version.version_no)
    ready = bool(synchronized and content is not None and metadata.get("source_hash") == source_hash(content))
    return {"status": "ready" if ready else "adoption_required" if synchronized else "original_sync_required"}


def publication_markdown(step_id: str, content: str) -> str:
    slug = step_id.removeprefix(STEP_PREFIX)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise HTTPException(404, "Рецепт не найден")
    # Match the accepted release's projection; the stored source stays untouched.
    body = re.sub(r"<!--.*?-->", "", content, flags=re.S)
    body = re.sub(r"^# [^\n]+\n", "", body).strip() + "\n"

    def media_url(match: re.Match) -> str:
        filename = match[1].removeprefix("media/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename) or filename in {".", ".."}:
            raise HTTPException(422, "Некорректный путь изображения рецепта")
        return f"](/course-assets/masterclass/media/15-recipes/{slug}/{filename})"

    return re.sub(r"\]\((media/[^)]+)\)", media_url, body)


def protected_parts(content: str) -> tuple:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    return (
        re.findall(r"<!--.*?-->", content, flags=re.S),
        re.findall(r"^[a-z][\w-]*\([ \t]*\r?\n.*?^\)[ \t]*\r?$", content, flags=re.M | re.S),
        re.findall(r"!\[[^]]*\]\([^\n]+\)", content),
        re.findall(r"(?<!!)\[[^]]*\]\(([^\n)]+)\)", content),
        re.findall(r"^# .*$", content, flags=re.M),
    )


def publish_recipe_source(
    db: Session, *, step_id: str, content: str,
    expected_version: int, admin: str, adopt: bool = False,
) -> dict:
    if not step_id.startswith(STEP_PREFIX):
        raise HTTPException(404, "Рецепт не найден")
    if len(content.encode("utf-8")) > MAX_MATERIAL_BYTES:
        raise HTTPException(413, "Текст материала превышает допустимый размер")
    try:
        item = material_item(db, step_id, for_update=True)
        current = latest_version(db, item)
        if current is None or current.version_no != expected_version:
            raise HTTPException(409, "Материал изменён. Получите актуальную версию")
        metadata = (item.metadata_json or {}).get(METADATA_KEY, {})
        if metadata.get("version") != current.version_no:
            raise HTTPException(409, "Сначала синхронизируйте оригинал калькулятора через существующий workflow")
        try:
            cards = validated_cards(metadata.get("cards"))
        except ValueError as exc:
            raise HTTPException(409, "Нет проверенных данных оригинала калькулятора") from exc
        body = publication_markdown(step_id, content)
        html = render_material(body, "markdown")
        previous = retained_source(current)
        if adopt:
            if source_hash(content) != metadata.get("source_hash") or html != current.text_content:
                raise HTTPException(409, "Исходник не совпадает с hash и опубликованным HTML. Проверьте принятый пакет")
        else:
            if previous is None or source_hash(previous) != metadata.get("source_hash"):
                raise HTTPException(409, "Сначала подключите точный оригинал Markdown через recipe-source")
            if protected_parts(content) != protected_parts(previous):
                raise HTTPException(409, "Данные карточки, изображения и вставки меняются через workflow рецептов")
        if previous == content and current.text_content == html:
            return get_material(db, step_id)
        result = publish_material(
            db, step_id=step_id, content=body, content_format="markdown",
            expected_version=expected_version, admin=admin, commit=False,
        )
        version = latest_version(db, item)
        # Complete the new uncommitted edition before exposing it or committing.
        version.blocks = [block for block in version.blocks if block.get("type") != "editorial_source"] + [
            {"type": "editorial_source", "format": "markdown", "content": content},
        ]
        publish_originals(db, {"materials": [{
            "step_id": step_id, "expected_version": result["version"],
            "source_hash": source_hash(content), "cards": cards,
        }]}, apply=True)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return get_material(db, step_id)


def restore_recipe_source(db: Session, *, step_id: str, version_no: int, expected_version: int, admin: str) -> dict:
    item = material_item(db, step_id)
    version = None if item is None else db.scalar(select(ContentItemVersion).where(
        ContentItemVersion.item_id == item.id, ContentItemVersion.version_no == version_no,
    ))
    if version is None:
        raise HTTPException(404, "Редакция материала не найдена")
    content = retained_source(version)
    if content is None:
        raise HTTPException(409, "Старая редакция не содержит полный Markdown. Восстановите через workflow рецептов")
    return publish_recipe_source(db, step_id=step_id, content=content, expected_version=expected_version, admin=admin)
