from __future__ import annotations

import json

from app.course_structure_service import publish_course_seed_additions
from app.database import SessionLocal


def main() -> None:
    with SessionLocal() as db:
        version = publish_course_seed_additions(db, admin="chat-managed-seed")
        print(json.dumps({
            "version": version.version_no,
            "created_by": version.created_by,
            "active": version.is_active,
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
