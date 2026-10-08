"""Edit allowlisted service email sources through the existing Git editor."""
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Response

from app.auth import require_admin
from app.course_material_routes import EditorialDraftSave, EditorialPublish
from app.github_content_editor import GitHubContentEditor
from app.service_email_templates import ROOT, SCHEMAS, compile_source, source_path


class ServiceEmailContentEditor(GitHubContentEditor):
    profile_name = "service-email"

    def source_path(self, step_id: str) -> str:
        return source_path(step_id)

    def validate_source(self, step_id: str, content: str) -> None:
        compile_source(step_id, content)


def editor():
    return ServiceEmailContentEditor()


def private_response(response: Response):
    response.headers.update({"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex, nofollow"})


def known_code(code):
    try:
        source_path(code)
    except KeyError as exc:
        raise HTTPException(404, "Неизвестный шаблон письма") from exc


router = APIRouter(prefix="/admin/api/editorial/service-emails", tags=["service-email-authoring"], dependencies=[Depends(private_response)])


@router.get("")
def templates(_: str = Depends(require_admin)):
    return {"templates": [{"code": code, "path": source_path(code), "sections": {
        name: sorted(variables) for name, variables in sections.items()
    }} for code, sections in SCHEMAS.items()]}


@router.get("/{code}")
def email_source(code: str, _: str = Depends(require_admin)):
    known_code(code)
    source = (ROOT / (code + ".md")).read_text(encoding="utf-8")
    return {**editor().load(code), "runtime_source": {
        "path": source_path(code), "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }}


@router.put("/{code}/draft")
def save_email_draft(code: str, body: EditorialDraftSave, admin: str = Depends(require_admin)):
    known_code(code)
    try:
        return editor().save_draft(code, content=body.content, expected_main_sha=body.expected_main_sha,
                                   expected_draft_sha=body.expected_draft_sha, admin=admin)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{code}/publish")
def publish_email_draft(code: str, body: EditorialPublish, admin: str = Depends(require_admin)):
    known_code(code)
    try:
        return editor().publish(code, expected_main_sha=body.expected_main_sha,
                                expected_draft_sha=body.expected_draft_sha, admin=admin)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
