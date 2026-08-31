"""Preflight the approved Masterclass day 6-20 assembly and matching product copy.

This script is intentionally executed inside the backend container. The regular
editor API cannot change technical step fields (for example contentKind/status),
while the chat-managed course assembly is allowed to do so. Days 1-5 and all
stable IDs are protected by explicit preflight assertions. The matching
product-catalog change is prepared from the active managed card so its other
owner changes are not replaced by seed defaults. Existing progress is retained
by stable step IDs; days 1–5 are copied byte-for-byte from the active version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy import func, select

from app.course_material_service import get_material
from app.course_structure_service import (
    DOCUMENT_TYPE,
    DOCUMENT_KEY,
    MANAGED_SCHEMA_VERSION,
    active_course_version,
    prepare_20_day_migration,
    runtime_manifest,
)
from app.database import SessionLocal
from app.managed_documents import publish_document
from app.models import MasterclassDayProgress, MasterclassStepProgress
from app.product_catalog_service import (
    active_product_catalog,
    normalize_product_catalog,
    publish_product_catalog,
)


def digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prepare_masterclass_catalog(current: dict) -> tuple[dict, bool]:
    result = normalize_product_catalog(current)
    masterclass = next(
        (item for item in result["products"] if item.get("code") == "masterclass"),
        None,
    )
    if masterclass is None:
        raise RuntimeError("Product catalog has no masterclass card")
    old = "21-дневная программа Мастер-класса"
    new = "20-дневная программа Мастер-класса"
    marketing = str(masterclass.get("marketing") or "")
    if old in marketing:
        masterclass["marketing"] = marketing.replace(old, new)
        return result, True
    if new not in marketing:
        raise RuntimeError("Masterclass product card has no recognized program wording")
    return result, False


def affected_progress_counts(db) -> tuple[int, int]:
    opened_days = int(
        db.scalar(
            select(func.count())
            .select_from(MasterclassDayProgress)
            .where(MasterclassDayProgress.day_number >= 6)
        )
        or 0
    )
    completed_steps = int(
        db.scalar(
            select(func.count())
            .select_from(MasterclassStepProgress)
            .where(MasterclassStepProgress.day_number >= 6)
        )
        or 0
    )
    return opened_days, completed_steps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--desired", type=Path, required=True)
    parser.add_argument("--expected-version", type=int, required=True)
    parser.add_argument("--admin", default="codex-masterclass-finalization")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    desired = json.loads(args.desired.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        active = active_course_version(db)
        if active.version_no != args.expected_version:
            raise SystemExit(
                f"Expected structure v{args.expected_version}, found v{active.version_no}"
            )
        next_version = active.version_no + 1
        proposed, changes = prepare_20_day_migration(
            active.payload,
            desired,
            next_version,
        )
        catalog_active = active_product_catalog(db)
        catalog_payload, catalog_changed = prepare_masterclass_catalog(
            catalog_active.payload
        )
        opened_days, completed_steps = affected_progress_counts(db)

        # Runtime normalization must preserve the approved 20-day topology.
        prepared = runtime_manifest(proposed)
        if [day["number"] for day in prepared["days"]] != list(range(1, 21)):
            raise SystemExit("Prepared structure failed the 20-day runtime topology check")

        unpublished: list[str] = []
        for day in prepared["days"]:
            if int(day["number"]) < 6:
                continue
            for step in day.get("steps", []):
                if (
                    step.get("kind") == "article"
                    and step.get("contentKind") != "tutorial"
                    and not step.get("hidden", False)
                    and not step.get("locked", False)
                ):
                    state = get_material(db, str(step["id"]))
                    if not state.get("published") or int(state.get("version") or 0) < 1:
                        unpublished.append(str(step["id"]))
        if unpublished:
            raise SystemExit("Visible articles are not published: " + ", ".join(unpublished))

        summary = {
            "course": DOCUMENT_KEY,
            "expected_version": active.version_no,
            "next_version": next_version,
            "days_1_5_sha256": digest(active.payload["days"][:5]),
            "changes": changes,
            "product_catalog_expected_version": catalog_active.version_no,
            "product_catalog_wording_changed": catalog_changed,
            "affected_opened_day_rows": opened_days,
            "affected_completed_step_rows": completed_steps,
        }
        if not args.apply:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return

        published = publish_document(
            db,
            document_type=DOCUMENT_TYPE,
            document_key=DOCUMENT_KEY,
            schema_version=MANAGED_SCHEMA_VERSION,
            payload=proposed,
            expected_version=active.version_no,
            admin=args.admin,
        )
        catalog_published = publish_product_catalog(
            db,
            payload=catalog_payload,
            expected_version=catalog_active.version_no,
            admin=args.admin,
        )
        summary["applied_course_version"] = published.version_no
        summary["applied_product_catalog_version"] = catalog_published.version_no
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
