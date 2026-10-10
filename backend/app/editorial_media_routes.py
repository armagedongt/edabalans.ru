from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy.orm import Session

from app.blog_draft_routes import DraftMedia, PRIVATE_HEADERS, require_blog_mutation, require_blog_admin
from app.database import get_db
from app.editorial_media import delivered_bytes, ingest, decode_scope, stored_bytes

router = APIRouter(tags=["editorial-media"])


class ImageUpload(DraftMedia):
    scope: str = Field(min_length=1, max_length=160)


@router.post("/admin/api/editorial/media")
def upload_image(body: ImageUpload, admin: str = Depends(require_blog_mutation), db: Session = Depends(get_db)):
    return ingest(db, scope=body.scope, source=body.model_dump(exclude={"scope"}), admin=admin)


@router.get("/admin/api/editorial/media/{token}/{name}")
def preview_image(token: str, name: str, _: str = Depends(require_blog_admin), db: Session = Depends(get_db)):
    raw, mime = stored_bytes(db, decode_scope(token), name)
    return Response(raw, media_type=mime, headers=PRIVATE_HEADERS)


@router.get("/editorial-media/{token}/{name}", include_in_schema=False)
def read_image(token: str, name: str, request: Request, db: Session = Depends(get_db)):
    raw, mime = delivered_bytes(db, token=token, name=name, request=request)
    # Permissions and publication are checked on every read, including previously cached URLs.
    return Response(raw, media_type=mime, headers=PRIVATE_HEADERS)
