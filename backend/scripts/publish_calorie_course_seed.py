"""Version the approved course structure; never migrate or erase member progress."""
import argparse
import json

from sqlalchemy import func, select

from app.calorie_course_service import (
    DOCUMENT_KEY, DOCUMENT_TYPE, MANAGED_SCHEMA_VERSION,
    normalize_editor_payload, seed_manifest,
)
from app.database import SessionLocal
from app.managed_documents import active_document, document_hash, publish_document
from app.models import CourseEvent, CourseStageProgress, CourseStepProgress


def publish_seed(db, *, expected_version: int, apply: bool) -> dict:
    current = active_document(db, DOCUMENT_TYPE, DOCUMENT_KEY)
    if current is None or current.version_no != expected_version:
        raise ValueError("Active structure differs from the reviewed version")
    seed = seed_manifest()
    if seed.get("launchReady") or len(seed["stages"]) != 3 or sum(len(s["steps"]) for s in seed["stages"]) != 15:
        raise ValueError("Expected the closed approved 3-module, 15-material seed")
    seed = normalize_editor_payload(seed, seed, current.version_no + 1)
    if current.content_hash == document_hash(seed):
        return {"changed": False, "version": current.version_no}
    if current.payload.get("launchReady"):
        raise ValueError("The active course is already open; structural replacement is blocked")
    counts = {
        model.__tablename__: db.scalar(select(func.count()).select_from(model).where(model.course_code == DOCUMENT_KEY))
        for model in (CourseStageProgress, CourseStepProgress, CourseEvent)
    }
    if any(counts.values()):
        raise ValueError("Existing member progress requires an approved transfer, not a seed replacement")
    result = {"changed": True, "applied": False, "previous_version": current.version_no, "progress_counts": counts, "stages": 3, "materials": 15}
    if apply:
        version = publish_document(
            db, document_type=DOCUMENT_TYPE, document_key=DOCUMENT_KEY,
            schema_version=MANAGED_SCHEMA_VERSION, payload=seed,
            expected_version=expected_version, admin="approved-calories-release-20260925",
        )
        result.update(applied=True, version=version.version_no)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        print(json.dumps(publish_seed(session, expected_version=args.expected_version, apply=args.apply)))
