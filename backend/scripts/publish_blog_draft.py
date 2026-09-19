"""Build and optionally upload one canonical Markdown article package.

The source files remain the portable canonical handoff. The API only receives an
exact, versioned copy for owner preview and moderation.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


PACKAGE_FIELDS = {
    "title", "excerpt", "category", "visibility", "editorial_status", "cta",
    "sources", "source_id", "hero", "media",
}
MEDIA_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,91}\.(?:png|jpg|webp)")
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def build_package(metadata_path: Path, markdown_path: Path, media_dir: Path, expected_version: int) -> tuple[str, dict]:
    facts = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(facts, dict):
        raise ValueError("metadata must be a JSON object")
    slug = str(facts.get("slug") or "").strip()
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("metadata.slug must contain lowercase latin letters, digits and hyphens")
    source_media = facts.get("media") or []
    if not isinstance(source_media, list):
        raise ValueError("metadata.media must be a list")
    media = []
    media_root = media_dir.resolve(strict=True)
    for item in source_media:
        if not isinstance(item, dict) or not item.get("name"):
            raise ValueError("every media item needs a name")
        value = deepcopy(item)
        name = str(value["name"])
        if not MEDIA_NAME_RE.fullmatch(name):
            raise ValueError(f"unsafe media name: {name}")
        media_path = (media_root / name).resolve(strict=True)
        if media_path.parent != media_root:
            raise ValueError(f"media file escapes media directory: {name}")
        value["content_base64"] = base64.b64encode(media_path.read_bytes()).decode("ascii")
        value.setdefault("alt", "")
        media.append(value)
    metadata = {
        key: value for key, value in facts.items()
        if key not in PACKAGE_FIELDS and key != "slug"
    }
    package = {
        "expected_version": expected_version,
        "title": facts.get("title"),
        "excerpt": facts.get("excerpt", ""),
        "category": facts.get("category"),
        "markdown": markdown_path.read_text(encoding="utf-8"),
        "visibility": facts.get("visibility", "public"),
        "editorial_status": facts.get("editorial_status", "moderation"),
        "cta": facts.get("cta"),
        "sources": facts.get("sources"),
        "source_id": facts.get("source_id"),
        "hero": facts.get("hero"),
        "media": media,
        "metadata": metadata,
    }
    return slug, package


def upload(api_base: str, slug: str, package: dict, username: str, password: str) -> dict:
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("unsafe blog slug")
    parsed = urlsplit(api_base)
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Blog API credentials require HTTPS; plain HTTP is allowed only for localhost")
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    request = Request(
        f"{api_base.rstrip('/')}/admin/api/blog/articles/{slug}",
        data=json.dumps(package, ensure_ascii=False).encode("utf-8"),
        method="PUT",
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Blog API returned {exc.code}: {detail}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Package and upload a Markdown article to blog moderation")
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    parser.add_argument("--media-dir", required=True, type=Path)
    parser.add_argument("--expected-version", type=int, default=0)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    slug, package = build_package(args.metadata, args.markdown, args.media_dir, args.expected_version)
    if args.dry_run:
        print(json.dumps({
            "slug": slug,
            "markdown_bytes": len(package["markdown"].encode("utf-8")),
            "media": [item["name"] for item in package["media"]],
            "visibility": package["visibility"],
            "editorial_status": package["editorial_status"],
        }, ensure_ascii=False, indent=2))
        return 0
    username = os.getenv("EDABALANS_ADMIN_USER", "")
    password = os.getenv("EDABALANS_ADMIN_PASSWORD", "")
    if not username or not password:
        print("Set EDABALANS_ADMIN_USER and EDABALANS_ADMIN_PASSWORD", file=sys.stderr)
        return 2
    result = upload(args.api_base, slug, package, username, password)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
