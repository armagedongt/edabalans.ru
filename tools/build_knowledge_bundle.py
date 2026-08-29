from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_bundle(manifest_path: Path, output_dir: Path) -> dict:
    project_root = manifest_path.resolve().parents[2]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    resources = []
    missing = []
    for entry in manifest.get("resources", []):
        source_path = project_root / entry["path"]
        if not source_path.is_file():
            missing.append(entry["path"])
            continue
        text = source_path.read_text(encoding="utf-8")
        resource_key = entry["resource_key"]
        resources.append({
            "resource_key": resource_key,
            "title": entry["title"],
            "contour": "editorial",
            "resource_kind": entry["resource_kind"],
            "role": entry["role"],
            "state": entry["state"],
            "storage_kind": "database",
            "canonical_uri": f"knowledge://resource/{resource_key}",
            "owner_module": entry.get("owner_module", "platform.knowledge"),
            "access_level": entry.get("access_level", "internal"),
            "text": text,
            "provenance": {
                "import_source": entry["path"],
                "origin": entry.get("origin", ""),
                "reviewed_at": entry.get("reviewed_at", "2026-08-29"),
            },
            "created_by": "knowledge-bundle-v1",
            "source_author": entry.get("source_author", "Сергей Воронцов"),
            "metadata": entry.get("metadata", {}),
        })
    if missing:
        raise ValueError("missing source files: " + ", ".join(missing))
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("resources.jsonl", resources),
        ("relations.jsonl", manifest.get("relations", [])),
        ("reviews.jsonl", manifest.get("reviews", [])),
    ):
        (output_dir / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
    return {
        "resources": len(resources),
        "relations": len(manifest.get("relations", [])),
        "reviews": len(manifest.get("reviews", [])),
        "output": str(output_dir.resolve()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a private server import bundle from tracked source files")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_bundle(args.manifest, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
