from typing import Annotated, Literal, Union
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.auth import require_admin
from app.blog_draft_routes import require_blog_mutation, PRIVATE_HEADERS, DraftMedia
from app.database import get_db
from app import course_structure_operations as operations

router = APIRouter()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Reorder(Strict):
    type: Literal["reorder"]
    unit: int = Field(ge=1, le=365)
    ids: list[str] = Field(min_length=1, max_length=300)


class Move(Strict):
    type: Literal["move"]
    unit: int = Field(ge=1, le=365)
    id: str = Field(min_length=1, max_length=160)
    before_id: str | None = Field(default=None, min_length=1, max_length=160)
    required_for_existing: bool


class AddArticle(Strict):
    type: Literal["add_article"]
    unit: int = Field(ge=1, le=365)
    id: str = Field(pattern=r"^[a-z0-9-]{1,160}$")
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2000)
    before_id: str | None = Field(default=None, min_length=1, max_length=160)
    required: bool
    required_for_existing: bool
    content: str = Field(min_length=1, max_length=500_000)
    media: list[DraftMedia] = Field(default_factory=list, max_length=8)


class OperationRequest(Strict):
    expected_version: int = Field(ge=1)
    operation: Annotated[Union[Reorder, Move, AddArticle], Field(discriminator="type")]


@router.post("/admin/api/courses/{course_code}/structure/operations/preview")
def preview(course_code: str, body: OperationRequest, response: Response,
            _: str = Depends(require_admin), db: Session = Depends(get_db)):
    response.headers.update(PRIVATE_HEADERS)
    return operations.preview(db, course_code, body.expected_version, body.operation.model_dump())


@router.post("/admin/api/courses/{course_code}/structure/operations/apply")
def apply(course_code: str, body: OperationRequest, response: Response,
          admin: str = Depends(require_blog_mutation), db: Session = Depends(get_db)):
    response.headers.update(PRIVATE_HEADERS)
    return operations.apply(db, course_code, body.expected_version, body.operation.model_dump(), admin)
