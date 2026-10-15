from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasicCredentials
from pydantic import BaseModel

from app.auth import admin_identity, require_admin, security
from app import travel_service as service
from starlette.responses import JSONResponse

STATIC = Path(__file__).parent / "static" / "travel"


def private(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"


router = APIRouter(dependencies=[Depends(private)])


class TravelBodyLimit:
    """Limit private publishing bodies before FastAPI parses JSON."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/admin/api/travel") or scope.get("method") not in {"PUT", "POST"}:
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > service.MAX_BYTES + 200_000:
                return await JSONResponse({"detail": "План слишком большой"}, status_code=413)(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break
        async def replay():
            if chunks:
                return chunks.pop(0)
            return await receive()
        return await self.app(scope, replay, send)


def write_guard(request: Request):
    origin = request.headers.get("origin")
    if request.headers.get("x-travel-write") != "1" or (origin and origin.rstrip("/") != str(request.base_url).rstrip("/")):
        raise HTTPException(403, "Недопустимый источник записи")


@router.get("/admin/travel", include_in_schema=False)
@router.get("/admin/travel/phases/{phase_id}", include_in_schema=False)
def legacy_page(phase_id: str = ""):
    if phase_id:
        try:
            service.identifier(phase_id)
        except service.TravelError as exc:
            raise HTTPException(404, str(exc)) from exc
    return RedirectResponse("/travel" + ("/phases/" + phase_id if phase_id else ""), status_code=303, headers={"Cache-Control": "no-store"})


@router.get("/travel", include_in_schema=False)
@router.get("/travel/phases/{phase_id}", include_in_schema=False)
def page(phase_id: str = ""):
    if phase_id:
        try:
            service.identifier(phase_id)
        except service.TravelError as exc:
            raise HTTPException(404, str(exc)) from exc
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@router.get("/admin/travel/assets/{name}", dependencies=[Depends(require_admin)], include_in_schema=False)
@router.get("/travel/assets/{name}", include_in_schema=False)
def asset(name: str):
    if name not in {"app.mjs", "calc.mjs", "style.css"}:
        raise HTTPException(404)
    media = "text/javascript" if name.endswith(".mjs") else "text/css"
    return FileResponse(STATIC / name, media_type=media, headers={"Cache-Control": "no-store"})


@router.get("/admin/api/travel/plan", dependencies=[Depends(require_admin)])
def get_plan():
    try:
        files, revision = service.snapshot()
        return {"model": service.compile_files(files), "revision": revision}
    except service.TravelError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/api/travel/plan")
def public_plan(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)):
    result = get_plan()
    result["canEdit"] = bool(admin_identity(request, credentials))
    return result


@router.get("/admin/api/travel/export", dependencies=[Depends(require_admin)])
def export_markdown():
    try:
        files, revision = service.snapshot()
        return {"files": files, "revision": revision}
    except service.TravelError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/admin/api/travel/phases/{phase_id}", dependencies=[Depends(require_admin)])
@router.get("/api/travel/phases/{phase_id}")
def phase(phase_id: str):
    try:
        return service.article(phase_id)
    except service.TravelError as exc:
        raise HTTPException(404, str(exc)) from exc


class SaveBody(BaseModel):
    revision: str
    model: dict


class PublishBody(BaseModel):
    revision: str
    files: dict[str, str]


@router.put("/admin/api/travel/plan", dependencies=[Depends(require_admin), Depends(write_guard)])
def save(body: SaveBody):
    try:
        return {"revision": service.save_model(body.model, body.revision)}
    except service.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (service.TravelError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/admin/api/travel/publish", dependencies=[Depends(require_admin), Depends(write_guard)])
def publish(body: PublishBody):
    try:
        return {"revision": service.publish(body.files, body.revision)}
    except service.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (service.TravelError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
