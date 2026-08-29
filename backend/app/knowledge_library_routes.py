from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.knowledge_library_service import (
    KnowledgeConflict,
    decide_review,
    knowledge_read,
    knowledge_search,
    library_summary,
    list_reviews,
    queue_review,
    record_usage,
    save_relation,
    save_resource,
    task_context,
)


router = APIRouter(prefix="/admin/api/library", tags=["knowledge-library-admin"])


class ResourceWrite(BaseModel):
    resource_key: str = Field(min_length=3, max_length=255)
    title: str = Field(min_length=1, max_length=1000)
    contour: str
    resource_kind: str = Field(min_length=1, max_length=64)
    role: str
    state: str
    storage_kind: str
    canonical_uri: str = Field(min_length=1, max_length=4000)
    owner_module: str = Field(min_length=1, max_length=128)
    access_level: str
    text: str = Field(default="", max_length=2_000_000)
    provenance: dict = Field(default_factory=dict)
    created_by: str = Field(default="owner", min_length=1, max_length=255)
    person_reference: str | None = Field(default=None, max_length=2000)
    source_author: str | None = Field(default=None, max_length=1000)
    source_date: datetime | None = None
    metadata: dict = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=0)


class RelationWrite(BaseModel):
    source_key: str = Field(min_length=3, max_length=255)
    target_key: str = Field(min_length=3, max_length=255)
    relation_type: str
    metadata: dict = Field(default_factory=dict)


class ReviewWrite(BaseModel):
    review_key: str = Field(min_length=3, max_length=255)
    review_kind: str
    title: str = Field(min_length=1, max_length=1000)
    resource_keys: list[str] = Field(default_factory=list, max_length=100)
    details: dict = Field(default_factory=dict)


class UsageWrite(BaseModel):
    source_uri: str = Field(min_length=3, max_length=4000)
    task_key: str = Field(min_length=1, max_length=255)
    destination: str = Field(min_length=1, max_length=2000)
    usage_kind: str
    excerpt_reference: str | None = Field(default=None, max_length=4000)
    output_uri: str | None = Field(default=None, max_length=4000)
    metadata: dict = Field(default_factory=dict)


class ReviewDecision(BaseModel):
    status: str = Field(pattern="^(resolved|dismissed)$")
    decision: dict = Field(default_factory=dict)


@router.get("/summary")
def summary(_: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return library_summary(db)


@router.get("/search")
def search(
    q: str = Query(default="", max_length=500),
    contour: str = Query(default="all", pattern="^(all|editorial|technical)$"),
    kind: list[str] | None = Query(default=None),
    include_restricted: bool = True,
    limit: int = Query(default=20, ge=1, le=100),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return knowledge_search(
        db, query=q, contour=contour, kinds=kind,
        include_restricted=include_restricted, limit=limit,
    )


@router.get("/read")
def read(
    uri: str = Query(min_length=1, max_length=4000),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    result = knowledge_read(db, uri)
    if result is None:
        raise HTTPException(status_code=404, detail="knowledge resource not found")
    return result


@router.get("/task-context")
def get_task_context(
    topic: str = Query(min_length=1, max_length=500),
    task_type: str = Query(min_length=1, max_length=80),
    product: str = Query(default="", max_length=120),
    surface: str = Query(default="internal", pattern="^(open|intensive|paid|internal)$"),
    limit: int = Query(default=20, ge=1, le=100),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return task_context(
        db, topic=topic, task_type=task_type, product=product,
        surface=surface, limit=limit,
    )


@router.put("/resources")
def put_resource(
    body: ResourceWrite,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return save_resource(db, **body.model_dump())
    except KnowledgeConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/relations")
def post_relation(
    body: RelationWrite,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return save_relation(db, **body.model_dump())
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/reviews")
def post_review(
    body: ReviewWrite,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return queue_review(db, **body.model_dump())
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/reviews")
def reviews(
    status: str = Query(default="pending", pattern="^(pending|resolved|dismissed|all)$"),
    limit: int = Query(default=100, ge=1, le=500),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_reviews(db, status=status, limit=limit)


@router.post("/reviews/{review_key}/decision")
def review_decision(
    review_key: str,
    body: ReviewDecision,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return decide_review(db, review_key=review_key, **body.model_dump())
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgeConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/usage")
def post_usage(
    body: UsageWrite,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return record_usage(db, **body.model_dump())
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
