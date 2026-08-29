from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.content_authoring_service import (
    RevisionConflict,
    authoring_summary,
    decide_candidate_group,
    get_authoring_group,
    list_authoring_groups,
    list_candidate_groups,
    save_authoring_item,
)
from app.content_service import (
    content_summary,
    get_content_item,
    list_content_comments,
    list_content_items,
)
from app.database import get_db
from app.models import ContentItem


router = APIRouter(prefix="/admin/api/content", tags=["content-admin"])


class AuthoringItemUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=400)
    text: str = Field(min_length=1, max_length=250_000)
    variant_label: str = Field(default="", max_length=120)
    editorial_status: str = Field(pattern="^(active|removed)$")


class CandidateDecision(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=80)
    pair_keys: list[str] = Field(min_length=1, max_length=500)
    action: str = Field(pattern="^(merge|reject)$")
    selected_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


@router.get("/summary")
def summary(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return content_summary(db)


@router.get("/items")
def items(
    q: str = Query(default="", max_length=255),
    source: str = Query(default="", max_length=32),
    sort: str = Query(default="date", pattern="^(date|views|likes|rating|comments|links)$"),
    has_links: str = Query(default="", pattern="^(|yes|no)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_content_items(
        db, q=q, source=source, sort=sort, has_links=has_links,
        limit=limit, offset=offset,
    )


@router.get("/items/{item_id}")
def item(item_id: uuid.UUID, _: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    result = get_content_item(db, item_id)
    if not result:
        raise HTTPException(status_code=404, detail="content item not found")
    return result


@router.get("/items/{item_id}/comments")
def comments(
    item_id: uuid.UUID,
    owner_only: bool = False,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    if not db.get(ContentItem, item_id):
        raise HTTPException(status_code=404, detail="content item not found")
    return list_content_comments(db, item_id, owner_only=owner_only)


@router.get("/authoring/summary")
def authoring_catalog_summary(
    _: str = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    return authoring_summary(db)


@router.get("/authoring/groups")
def authoring_groups(
    q: str = Query(default="", max_length=255),
    source: str = Query(default="", max_length=32),
    shape: str = Query(default="all", pattern="^(all|families|singletons)$"),
    purpose: str = Query(default="", max_length=64),
    editorial_status: str = Query(default="active", pattern="^(active|removed|all)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=50),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return list_authoring_groups(
        db, q=q, source=source, shape=shape, purpose=purpose,
        editorial_status=editorial_status, offset=offset, limit=limit
    )


@router.get("/authoring/groups/{group_key}")
def authoring_group(
    group_key: str,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    result = get_authoring_group(db, group_key)
    if not result:
        raise HTTPException(status_code=404, detail="content group not found")
    return result


@router.put("/authoring/items/{item_id}")
def update_authoring_item(
    item_id: uuid.UUID,
    body: AuthoringItemUpdate,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return save_authoring_item(db, item_id, **body.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RevisionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/authoring/candidates")
def authoring_candidates(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=50),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return list_candidate_groups(db, offset=offset, limit=limit)


@router.post("/authoring/candidates/decision")
def authoring_candidate_decision(
    body: CandidateDecision,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return decide_candidate_group(db, **body.model_dump())
    except RevisionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
