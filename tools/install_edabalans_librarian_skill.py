"""Install or verify the project-owned edabalans Librarian skill in Codex."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "content" / "knowledge" / "skill" / "edabalans-librarian" / "SKILL.md"


def default_destination() -> Path:
    codex_root = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    return codex_root / "skills" / "edabalans-librarian" / "SKILL.md"


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


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


def status(source: Path, destination: Path) -> dict[str, str | bool | None]:
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
    if not source.is_file():
        raise FileNotFoundError(source)
    replace_with_copy(source, destination)
    return status(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--install", action="store_true")
    parser.add_argument("--destination", type=Path, default=default_destination())
    args = parser.parse_args()
    result = install(SOURCE, args.destination) if args.install else status(SOURCE, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "current" else 1


if __name__ == "__main__":
    raise SystemExit(main())
