from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.managed_documents import version_history
from app.public_site_content_service import (
    DOCUMENTS,
    DOCUMENT_TYPE,
    active_public_site_document,
    publish_public_site_document,
    serialize_public_site_document,
    serialize_public_site_rendered_document,
)


router = APIRouter(tags=["public-site"])


class PublicSiteContentUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    markdown: str = Field(min_length=1, max_length=250_000)


@router.get("/api/public-site/content/{slug}")
def public_site_content(slug: str, db: Session = Depends(get_db)) -> dict:
    return serialize_public_site_rendered_document(active_public_site_document(db, slug))


@router.get("/admin/api/public-site/content")
def public_site_content_index(
    _: str = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    return {
        "ok": True,
        "documents": [
            serialize_public_site_document(active_public_site_document(db, slug))
            for slug in DOCUMENTS
        ],
    }


@router.get("/admin/api/public-site/content/{slug}")
def public_site_content_editor(
    slug: str, _: str = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    active = active_public_site_document(db, slug)
    return {
        "ok": True,
        "active": serialize_public_site_document(active),
        "history": [
            {
                "version": item.version_no,
                "updated_at": item.created_at.isoformat(),
                "updated_by": item.created_by,
                "active": item.is_active,
            }
            for item in version_history(db, DOCUMENT_TYPE, slug)
        ],
    }


@router.put("/admin/api/public-site/content/{slug}")
def update_public_site_content(
    slug: str,
    body: PublicSiteContentUpdate,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    version = publish_public_site_document(
        db,
        slug=slug,
        markdown=body.markdown,
        expected_version=body.expected_version,
        admin=admin,
    )
    return {"ok": True, "active": serialize_public_site_document(version)}
