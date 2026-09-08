"""Hide the superseded first-day messenger link step.

Revision ID: 20260908_0039
Revises: 20260908_0038
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260908_0039"
down_revision = "20260908_0038"
branch_labels = None
depends_on = None


def document_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def upgrade() -> None:
    documents = sa.table(
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
    bind = op.get_bind()
    current = bind.execute(
        sa.select(documents).where(
            documents.c.document_type == "course-structure",
            documents.c.document_key == "masterclass-21",
            documents.c.is_active.is_(True),
        )
    ).mappings().one_or_none()
    if current is None:
        return

    payload = deepcopy(current["payload"])
    if isinstance(payload, str):
        payload = json.loads(payload)
    step = next(
        (
            item
            for item in payload.get("days", [{}])[0].get("steps", [])
            if item.get("id") == "day-01-messenger-link"
        ),
        None,
    )
    if step is None or step.get("hidden", False):
        return
    step["hidden"] = True

    bind.execute(
        documents.update().where(documents.c.id == current["id"]).values(is_active=False)
    )
    bind.execute(
        documents.insert().values(
            document_type=current["document_type"],
            document_key=current["document_key"],
            schema_version=current["schema_version"],
            version_no=current["version_no"] + 1,
            payload=payload,
            content_hash=document_hash(payload),
            created_by="migration-hide-legacy-messenger-step",
            is_active=True,
        )
    )


def downgrade() -> None:
    # Course structure is versioned content. Reverting a deploy must not silently
    # reactivate an older participant-facing version.
    pass
