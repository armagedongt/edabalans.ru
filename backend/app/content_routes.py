from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.content_service import content_summary, get_content_item, list_content_items
from app.database import get_db


router = APIRouter(prefix="/admin/api/content", tags=["content-admin"])


@router.get("/summary")
def summary(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return content_summary(db)


@router.get("/items")
def items(
    q: str = Query(default="", max_length=255),
    source: str = Query(default="", max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_content_items(db, q=q, source=source, limit=limit, offset=offset)


@router.get("/items/{item_id}")
def item(item_id: uuid.UUID, _: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    result = get_content_item(db, item_id)
    if not result:
        raise HTTPException(status_code=404, detail="content item not found")
    return result
