from __future__ import annotations

import argparse
import sys

from app.database import SessionLocal
from app.public_site_content_service import (
    DOCUMENTS,
    active_public_site_document,
    publish_public_site_document,
    serialize_public_site_document,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish one homepage Markdown document")
    parser.add_argument("slug", choices=tuple(DOCUMENTS))
    parser.add_argument("--expected-version", type=int, required=True)
    parser.add_argument("--admin", default="codex-content-publisher")
    args = parser.parse_args()
    markdown = sys.stdin.read()
    if not markdown.strip():
        parser.error("Markdown must be supplied through stdin")
    with SessionLocal() as db:
        active_public_site_document(db, args.slug)
        version = publish_public_site_document(
            db,
            slug=args.slug,
            markdown=markdown,
            expected_version=args.expected_version,
            admin=args.admin,
        )
        print(serialize_public_site_document(version)["version"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
