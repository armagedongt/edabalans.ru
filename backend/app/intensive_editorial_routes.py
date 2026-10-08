from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, Depends, HTTPException, Response

from app.auth import require_admin
from app.course_material_routes import EditorialDraftSave, EditorialPublish
from app.github_content_editor import GitHubContentEditor
from app.intensive_onepage import MARKERS, SOURCE, render_article


SOURCE_ID = "intensive-onepage"
SOURCE_PATH = "content/masterclass/editorial/weight-loss-roadmap.md"


class IntensiveContentEditor(GitHubContentEditor):
    profile_name = "intensive"

    def source_path(self, step_id: str) -> str:
        if step_id != SOURCE_ID:
            raise KeyError("Неизвестный оригинал интенсива")
        return SOURCE_PATH

    def validate_source(self, step_id: str, content: str) -> None:
        self.source_path(step_id)
        if len(content.encode("utf-8")) > 500_000 or not re.match(r"\A\ufeff?# [^\n]+", content):
            raise ValueError("Интенсив должен содержать заголовок первого уровня и допустимый объём Markdown")
        structural_comments = re.compile(r"<!--\s*(intensive:[a-z0-9:-]+)\s*-->")
        original = [marker for marker in structural_comments.findall(SOURCE.read_text(encoding="utf-8"))
                    if marker in MARKERS]
        edited = [marker for marker in structural_comments.findall(content) if marker in MARKERS]
        if edited != original:
            raise ValueError("Сохраните порядок структурных маркеров интенсива; структуру меняют через Codex")
        render_article(content)


def editor() -> IntensiveContentEditor:
    return IntensiveContentEditor()


def private_response(response: Response) -> None:
    response.headers.update({"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex, nofollow"})


router = APIRouter(tags=["intensive-authoring"], dependencies=[Depends(private_response)])


@router.get("/admin/api/editorial/intensive")
def intensive_source(_: str = Depends(require_admin)) -> dict:
    payload = editor().load(SOURCE_ID)
    source = SOURCE.read_text(encoding="utf-8")
    return {**payload, "runtime_source": {
        "path": SOURCE_PATH, "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }}


@router.put("/admin/api/editorial/intensive/draft")
def save_intensive_draft(body: EditorialDraftSave, admin: str = Depends(require_admin)) -> dict:
    try:
        return editor().save_draft(SOURCE_ID, content=body.content, expected_main_sha=body.expected_main_sha,
                                   expected_draft_sha=body.expected_draft_sha, admin=admin)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/admin/api/editorial/intensive/publish")
def publish_intensive_draft(body: EditorialPublish, admin: str = Depends(require_admin)) -> dict:
    return editor().publish(SOURCE_ID, expected_main_sha=body.expected_main_sha,
                            expected_draft_sha=body.expected_draft_sha, admin=admin)
