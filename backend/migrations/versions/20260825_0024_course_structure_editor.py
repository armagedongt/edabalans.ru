"""Add versioned course structure and stable masterclass check IDs.

Revision ID: 20260825_0024
Revises: 20260825_0023
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = "20260825_0024"
down_revision = "20260825_0023"
branch_labels = None
depends_on = None


def baseline_manifest() -> dict:
    path = Path(__file__).resolve().parents[3] / "content" / "masterclass" / "course" / "course.json"
    return json.loads(path.read_text(encoding="utf-8"))


def check_id(day: int, index: int) -> str:
    return f"day-{day}-check-{index + 1}"


def upgrade() -> None:
    op.create_table(
        "managed_document_versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("document_key", sa.String(length=160), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_type", "document_key", "version_no",
            name="uq_managed_document_version",
        ),
    )
    op.create_index(
        "ix_managed_document_lookup",
        "managed_document_versions",
        ["document_type", "document_key", "version_no"],
    )
    op.create_index(
        "uq_managed_document_active",
        "managed_document_versions",
        ["document_type", "document_key"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    manifest = baseline_manifest()
    normalized = json.loads(json.dumps(manifest, ensure_ascii=False))
    for day in normalized["days"]:
        day_number = int(day["number"])
        day["checks"] = [
            item if isinstance(item, dict) else {
                "id": check_id(day_number, index),
                "text": str(item),
                "required": True,
                "hidden": False,
            }
            for index, item in enumerate(day.get("checks", []))
        ]
        for step in day.get("steps", []):
            step.setdefault("hidden", False)
            if step.get("contentKind") == "imported":
                step.setdefault("contentPageTitle", step.get("title"))
    content_hash = hashlib.sha256(
        json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    managed_documents = sa.table(
        "managed_document_versions",
        sa.column("document_type", sa.String()),
        sa.column("document_key", sa.String()),
        sa.column("schema_version", sa.Integer()),
        sa.column("version_no", sa.Integer()),
        sa.column("payload", sa.JSON()),
        sa.column("content_hash", sa.String()),
        sa.column("created_by", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.get_bind().execute(
        managed_documents.insert().values(
            document_type="course-structure",
            document_key="masterclass-21",
            schema_version=1,
            version_no=1,
            payload=normalized,
            content_hash=content_hash,
            created_by="migration-seed",
            is_active=True,
        )
    )

    op.add_column(
        "masterclass_day_progress",
        sa.Column("structure_revision_no", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "masterclass_day_progress",
        sa.Column("required_step_ids", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
    )
    op.add_column(
        "masterclass_day_progress",
        sa.Column("required_check_ids", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
    )

    days = {int(day["number"]): day for day in normalized["days"]}
    bind = op.get_bind()

    progress_table = sa.table(
        "masterclass_day_progress",
        sa.column("id", sa.Uuid()),
        sa.column("day_number", sa.Integer()),
        sa.column("checkmarks", sa.JSON()),
        sa.column("required_step_ids", sa.JSON()),
        sa.column("required_check_ids", sa.JSON()),
    )
    day_rows = bind.execute(
        sa.select(progress_table.c.id, progress_table.c.day_number, progress_table.c.checkmarks)
    ).mappings()
    for row in day_rows:
        day_number = int(row["day_number"])
        day = days.get(day_number)
        if day is None:
            raise RuntimeError(f"Cannot backfill masterclass day progress {row['id']}: unknown day")
        checks = list(day.get("checks") or [])
        raw_marks = row["checkmarks"] or {}
        if isinstance(raw_marks, str):
            raw_marks = json.loads(raw_marks)
        mapped_marks: dict[str, bool] = {}
        for key, value in raw_marks.items():
            index = int(key)
            if index < 0 or index >= len(checks):
                raise RuntimeError(
                    f"Cannot backfill masterclass day progress {row['id']}: check index is outside active baseline"
                )
            mapped_marks[check_id(day_number, index)] = bool(value)
        bind.execute(
            progress_table.update()
            .where(progress_table.c.id == row["id"])
            .values(
                checkmarks=mapped_marks,
                required_step_ids=[
                    step["id"] for step in day.get("steps", []) if step.get("required", True)
                ],
                required_check_ids=[check_id(day_number, index) for index in range(len(checks))],
            )
        )

def downgrade() -> None:
    op.drop_column("masterclass_day_progress", "required_check_ids")
    op.drop_column("masterclass_day_progress", "required_step_ids")
    op.drop_column("masterclass_day_progress", "structure_revision_no")
    op.drop_index("uq_managed_document_active", table_name="managed_document_versions")
    op.drop_index("ix_managed_document_lookup", table_name="managed_document_versions")
    op.drop_table("managed_document_versions")
