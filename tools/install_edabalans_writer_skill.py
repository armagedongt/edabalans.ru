"""Install or verify the project-owned edabalans writer skill in Codex."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "content" / "author-voice" / "skill" / "edabalans-writer" / "SKILL.md"
MANIFEST = SOURCE.parent / "assets" / "skill-manifest.json"


def default_destination() -> Path:
    codex_root = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    return codex_root / "skills" / "edabalans-writer" / "SKILL.md"


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    data = path.read_bytes()
    if path.suffix.lower() in {".md", ".json"}:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def canonical_text_digest(path: Path) -> str | None:
    """Hash project text independently of the checkout's newline convention."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def replace_with_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def sync_status(source: Path, destination: Path) -> dict[str, str | bool | None]:
    source_hash = digest(source)
    destination_hash = digest(destination)
    if source_hash is None:
        raise FileNotFoundError(source)
    linked = destination.exists() and source.samefile(destination)
    return {
        "status": "current" if source_hash == destination_hash else "outdated",
        "source": str(source),
        "destination": str(destination),
        "source_hash": source_hash,
        "destination_hash": destination_hash,
        "hard_linked": linked,
        "install_mode": "managed_copy",
    }


def install(source: Path, destination: Path) -> dict[str, str | bool | None]:
    if not source.exists():
        raise FileNotFoundError(source)
    replace_with_copy(source, destination)
    result = sync_status(source, destination)
    if source == SOURCE and MANIFEST.exists():
        manifest_destination = destination.parent / "assets" / MANIFEST.name
        replace_with_copy(MANIFEST, manifest_destination)
        result.update(package_status(destination))
    return result


def package_status(destination: Path) -> dict[str, object]:
    if not MANIFEST.is_file():
        return {"package_status": "outdated", "package_errors": [f"missing manifest: {MANIFEST}"]}
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"package_status": "outdated", "package_errors": [f"invalid manifest: {exc}"]}
    errors: list[str] = []
    files = manifest.get("files") or []
    if not manifest.get("package_version") or not isinstance(files, list):
        errors.append("manifest requires package_version and files")
    for item in files:
        relative = item.get("path") if isinstance(item, dict) else None
        expected = item.get("sha256") if isinstance(item, dict) else None
        path = PROJECT_ROOT / str(relative or "")
        if not relative or not expected or canonical_text_digest(path) != expected:
            errors.append(f"stale or missing canonical dependency: {relative}")
    installed_manifest = destination.parent / "assets" / MANIFEST.name
    if digest(installed_manifest) != digest(MANIFEST):
        errors.append("installed skill manifest is missing or stale")
    return {
        "package_version": manifest.get("package_version"),
        "package_status": "current" if not errors else "outdated",
        "package_errors": errors,
        "manifest": str(MANIFEST),
        "installed_manifest": str(installed_manifest),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--install", action="store_true")
    parser.add_argument("--destination", type=Path, default=default_destination())
    args = parser.parse_args()
    if args.install:
        result = install(SOURCE, args.destination)
    else:
        result = sync_status(SOURCE, args.destination)
        result.update(package_status(args.destination))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "current" and result.get("package_status") == "current" else 1


if __name__ == "__main__":
    raise SystemExit(main())
