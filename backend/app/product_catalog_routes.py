from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.managed_documents import restore_document, version_history
from app.product_catalog_service import (
    DOCUMENT_KEY, DOCUMENT_TYPE, active_product_catalog, catalog_payload,
    normalize_product_catalog, publish_product_catalog,
)
from app.course_structure_service import serialize_version


router = APIRouter(tags=["product-catalog-editor"])


class CatalogUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    payload: dict


class RestoreUpdate(BaseModel):
    expected_version: int = Field(ge=1)


def editor_payload(db: Session) -> dict:
    active = active_product_catalog(db)
    serialized = serialize_version(active)
    serialized["manifest"] = catalog_payload(db)
    return {"ok": True, "active": serialized, "history": [serialize_version(item, include_payload=False) for item in version_history(db, DOCUMENT_TYPE, DOCUMENT_KEY)]}


@router.get("/admin/api/product-catalog")
def get_catalog(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return editor_payload(db)


@router.put("/admin/api/product-catalog")
def save_catalog(body: CatalogUpdate, admin: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    publish_product_catalog(db, payload=body.payload, expected_version=body.expected_version, admin=admin)
    return editor_payload(db)


@router.post("/admin/api/product-catalog/versions/{version_no}/restore")
def restore_catalog(version_no: int, body: RestoreUpdate, admin: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    restore_document(db, document_type=DOCUMENT_TYPE, document_key=DOCUMENT_KEY, version_no=version_no, expected_version=body.expected_version, admin=admin, prepare_payload=lambda source, current, _: normalize_product_catalog(source))
    return editor_payload(db)
