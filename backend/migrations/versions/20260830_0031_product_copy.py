"""Publish owner-approved recordings and consultation copy.

Revision ID: 20260830_0031
Revises: 20260829_0030
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260830_0031"
down_revision = "20260829_0030"
branch_labels = None
depends_on = None


CREATED_BY = "migration:20260830_0031"
PRODUCT_COPY = {
    "recordings": {
        "shortName": "Два реальных разбора",
        "fullName": "Два реальных разбора участников Мастер-класса прошлых потоков",
        "descriptor": "Оригиналы дневника и запись всей консультации.",
    },
    "consultation": {
        "shortName": "Индивидуальная консультация",
        "fullName": "Индивидуальная консультация",
        "descriptor": (
            "Разбор дневника питания, определение плана действий и ответы на любые вопросы."
        ),
    },
}


def payload_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def managed_documents() -> sa.Table:
    return sa.table(
        "managed_document_versions",
        sa.column("id", sa.Uuid()),
        sa.column("document_type", sa.String()),
        sa.column("document_key", sa.String()),
        sa.column("schema_version", sa.Integer()),
        sa.column("version_no", sa.Integer()),
        sa.column("payload", sa.JSON()),
        sa.column("content_hash", sa.String()),
        sa.column("created_by", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )


def apply_product_copy(source_payload: dict | str) -> tuple[dict, bool]:
    payload = deepcopy(source_payload)
    if isinstance(payload, str):
        payload = json.loads(payload)
    products = {item.get("code"): item for item in payload.get("products", [])}
    if not set(PRODUCT_COPY).issubset(products):
        raise RuntimeError("product-catalog/core is missing required products")

    changed = False
    for code, approved in PRODUCT_COPY.items():
        for field, value in approved.items():
            if products[code].get(field) != value:
                products[code][field] = value
                changed = True
    return payload, changed


def upgrade() -> None:
    connection = op.get_bind()
    documents = managed_documents()
    current = connection.execute(
        sa.select(documents).where(
            documents.c.document_type == "product-catalog",
            documents.c.document_key == "core",
            documents.c.is_active.is_(True),
        )
    ).mappings().first()
    if current is None:
        return

    payload, changed = apply_product_copy(current["payload"])
    if not changed:
        return

    next_version = connection.scalar(
        sa.select(sa.func.max(documents.c.version_no)).where(
            documents.c.document_type == "product-catalog",
            documents.c.document_key == "core",
        )
    ) + 1
    connection.execute(
        documents.update()
        .where(documents.c.id == current["id"])
        .values(is_active=False)
    )
    connection.execute(
        documents.insert().values(
            document_type="product-catalog",
            document_key="core",
            schema_version=current["schema_version"],
            version_no=next_version,
            payload=payload,
            content_hash=payload_hash(payload),
            created_by=CREATED_BY,
            is_active=True,
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    documents = managed_documents()
    current = connection.execute(
        sa.select(documents).where(
            documents.c.document_type == "product-catalog",
            documents.c.document_key == "core",
            documents.c.is_active.is_(True),
        )
    ).mappings().first()
    if current is None or current["created_by"] != CREATED_BY:
        return
    previous = connection.execute(
        sa.select(documents)
        .where(
            documents.c.document_type == "product-catalog",
            documents.c.document_key == "core",
            documents.c.version_no < current["version_no"],
        )
        .order_by(documents.c.version_no.desc())
        .limit(1)
    ).mappings().first()
    if previous is None:
        return
    connection.execute(documents.delete().where(documents.c.id == current["id"]))
    connection.execute(
        documents.update()
        .where(documents.c.id == previous["id"])
        .values(is_active=True)
    )
