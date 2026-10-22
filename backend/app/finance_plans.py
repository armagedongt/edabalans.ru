"""Private scenario snapshots in the existing managed-document store."""
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.managed_documents import document_hash
from app.models import ManagedDocumentVersion

DOCUMENT_TYPE = "finance-plan"
PARAMETERS = set("paid organic conversion cpl minPrice standardPrice consultTariff consultCap minShare standardShare consultShare digitalRate digitalAverage consultRate supportRate supportPrice supportMonths clubEnabled clubRate clubPrice clubMonths opex weeklyCap timeUnit feeRate".split())
SPLIT_PARAMETERS = {"paidConversion30", "paidConversionLater", "organicConversion30", "organicConversionLater"}


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    club: float = Field(ge=0)
    club_enabled: bool
    income: float
    margin: float
    ads: float = Field(ge=0)
    opex: float = Field(ge=0)
    turnover: float = Field(ge=0)


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(default="План", min_length=1, max_length=120)
    parameters: dict[str, float | bool]
    summary: Summary
    legacy: bool = False

    @field_validator("parameters", mode="before")
    @classmethod
    def validate_parameters(cls, values):
        import math
        if not isinstance(values, dict) or set(values) not in (PARAMETERS, PARAMETERS | SPLIT_PARAMETERS):
            raise ValueError("Нужен полный набор параметров модели")
        for key, value in values.items():
            if key == "clubEnabled":
                if type(value) is not bool:
                    raise ValueError("Неверное состояние клуба")
            elif type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e12:
                raise ValueError("Неверное числовое значение")
        if SPLIT_PARAMETERS <= values.keys():
            for source in ("paid", "organic"):
                total = values[source + "Conversion30"] + values[source + "ConversionLater"]
                if total > 100:
                    raise ValueError("Сумма конверсий не может превышать 100%")
            if not math.isclose(values["conversion"], values["paidConversion30"] + values["paidConversionLater"], abs_tol=1e-8):
                raise ValueError("Общая платная конверсия не совпадает с суммой")
        return values


def private(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/admin/api/finance/plans", dependencies=[Depends(require_admin), Depends(private)])


def write_guard(request: Request):
    origin = request.headers.get("origin")
    if request.headers.get("x-finance-write") != "1" or (origin and origin.rstrip("/") != str(request.base_url).rstrip("/")):
        raise HTTPException(403, "Недопустимый источник записи")


def serialize(row):
    return {"id": str(row.id), "saved_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(), **row.payload}


@router.get("")
def list_plans(db: Session = Depends(get_db)):
    rows = db.scalars(select(ManagedDocumentVersion).where(
        ManagedDocumentVersion.document_type == DOCUMENT_TYPE,
        ManagedDocumentVersion.is_active.is_(True),
    ).order_by(ManagedDocumentVersion.created_at.desc(), ManagedDocumentVersion.id.desc()))
    return {"plans": [serialize(row) for row in rows]}


@router.post("", dependencies=[Depends(write_guard)])
def save_plan(body: PlanIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    payload = body.model_dump(exclude={"legacy"})
    key = "legacy-" + document_hash(payload["parameters"]) if body.legacy else str(uuid.uuid4())
    def existing():
        return db.scalar(select(ManagedDocumentVersion).where(
            ManagedDocumentVersion.document_type == DOCUMENT_TYPE,
            ManagedDocumentVersion.document_key == key,
        ))
    if body.legacy and (previous := existing()) is not None:
        return {"plan": serialize(previous) if previous.is_active else None}
    row = ManagedDocumentVersion(document_type=DOCUMENT_TYPE, document_key=key,
        schema_version=2 if SPLIT_PARAMETERS <= body.parameters.keys() else 1,
        version_no=1, payload=payload, content_hash=document_hash(payload),
        created_by=admin, is_active=True, created_at=datetime.now(timezone.utc))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not body.legacy or (previous := existing()) is None:
            raise
        return {"plan": serialize(previous) if previous.is_active else None}
    db.refresh(row)
    return {"plan": serialize(row)}


@router.delete("/{plan_id}", dependencies=[Depends(write_guard)])
def delete_plan(plan_id: uuid.UUID, db: Session = Depends(get_db)):
    row = db.scalar(select(ManagedDocumentVersion).where(
        ManagedDocumentVersion.id == plan_id,
        ManagedDocumentVersion.document_type == DOCUMENT_TYPE,
        ManagedDocumentVersion.is_active.is_(True),
    ))
    if row is None:
        raise HTTPException(404, "План не найден")
    row.is_active = False
    db.commit()
    return {"deleted": str(row.id)}
