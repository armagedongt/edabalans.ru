from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ManagedDocumentVersion


RETAIN_VERSIONS = 20


def document_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def active_document(
    db: Session, document_type: str, document_key: str
) -> ManagedDocumentVersion | None:
    return db.scalar(
        select(ManagedDocumentVersion).where(
            ManagedDocumentVersion.document_type == document_type,
            ManagedDocumentVersion.document_key == document_key,
            ManagedDocumentVersion.is_active.is_(True),
        )
    )


def ensure_seed_document(
    db: Session,
    *,
    document_type: str,
    document_key: str,
    schema_version: int,
    payload: dict,
) -> ManagedDocumentVersion:
    current = active_document(db, document_type, document_key)
    if current is not None:
        return current
    version = ManagedDocumentVersion(
        document_type=document_type,
        document_key=document_key,
        schema_version=schema_version,
        version_no=1,
        payload=deepcopy(payload),
        content_hash=document_hash(payload),
        created_by="system-seed",
        is_active=True,
    )
    db.add(version)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        current = active_document(db, document_type, document_key)
        if current is None:
            raise
        return current
    db.refresh(version)
    return version


def version_history(
    db: Session, document_type: str, document_key: str
) -> list[ManagedDocumentVersion]:
    return list(
        db.scalars(
            select(ManagedDocumentVersion)
            .where(
                ManagedDocumentVersion.document_type == document_type,
                ManagedDocumentVersion.document_key == document_key,
            )
            .order_by(ManagedDocumentVersion.version_no.desc())
            .limit(RETAIN_VERSIONS)
        )
    )


def publish_document(
    db: Session,
    *,
    document_type: str,
    document_key: str,
    schema_version: int,
    payload: dict,
    expected_version: int,
    admin: str,
) -> ManagedDocumentVersion:
    current = db.scalar(
        select(ManagedDocumentVersion)
        .where(
            ManagedDocumentVersion.document_type == document_type,
            ManagedDocumentVersion.document_key == document_key,
            ManagedDocumentVersion.is_active.is_(True),
        )
        .with_for_update()
    )
    if current is None or current.version_no != expected_version:
        raise HTTPException(
            status_code=409,
            detail="Структура уже изменена в другой вкладке. Обновите страницу перед сохранением",
        )
    payload_hash = document_hash(payload)
    if payload_hash == current.content_hash:
        return current

    next_version = current.version_no + 1
    current.is_active = False
    db.flush()
    version = ManagedDocumentVersion(
        document_type=document_type,
        document_key=document_key,
        schema_version=schema_version,
        version_no=next_version,
        payload=deepcopy(payload),
        content_hash=payload_hash,
        created_by=admin,
        is_active=True,
    )
    db.add(version)
    try:
        db.flush()
        keep_ids = list(
            db.scalars(
                select(ManagedDocumentVersion.id)
                .where(
                    ManagedDocumentVersion.document_type == document_type,
                    ManagedDocumentVersion.document_key == document_key,
                )
                .order_by(ManagedDocumentVersion.version_no.desc())
                .limit(RETAIN_VERSIONS)
            )
        )
        if keep_ids:
            db.execute(
                delete(ManagedDocumentVersion).where(
                    ManagedDocumentVersion.document_type == document_type,
                    ManagedDocumentVersion.document_key == document_key,
                    ManagedDocumentVersion.is_active.is_(False),
                    ManagedDocumentVersion.id.not_in(keep_ids),
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Структура уже изменена в другой вкладке. Обновите страницу перед сохранением",
        ) from exc
    db.refresh(version)
    return version


def restore_document(
    db: Session,
    *,
    document_type: str,
    document_key: str,
    version_no: int,
    expected_version: int,
    admin: str,
    prepare_payload,
) -> ManagedDocumentVersion:
    source = db.scalar(
        select(ManagedDocumentVersion).where(
            ManagedDocumentVersion.document_type == document_type,
            ManagedDocumentVersion.document_key == document_key,
            ManagedDocumentVersion.version_no == version_no,
        )
    )
    if source is None:
        raise HTTPException(404, "Редакция не найдена")
    current = active_document(db, document_type, document_key)
    if current is None:
        raise HTTPException(409, "Активная редакция не найдена")
    payload = prepare_payload(deepcopy(source.payload), deepcopy(current.payload), expected_version + 1)
    return publish_document(
        db,
        document_type=document_type,
        document_key=document_key,
        schema_version=source.schema_version,
        payload=payload,
        expected_version=expected_version,
        admin=admin,
    )
