"""Install or verify the project-owned edabalans writer skill in Codex."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "content" / "author-voice" / "skill" / "edabalans-writer" / "SKILL.md"


def default_destination() -> Path:
    codex_root = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    return codex_root / "skills" / "edabalans-writer" / "SKILL.md"


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sync_status(source: Path, destination: Path) -> dict[str, str | bool | None]:
    source_hash = digest(source)
    destination_hash = digest(destination)
    if source_hash is None:
        raise FileNotFoundError(source)
    linked = destination.exists() and source.samefile(destination)
    return {
        "status": "current" if source_hash == destination_hash and linked else "outdated",
        "source": str(source),
        "destination": str(destination),
        "source_hash": source_hash,
        "destination_hash": destination_hash,
        "hard_linked": linked,
    }


def install(source: Path, destination: Path) -> dict[str, str | bool | None]:
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not source.samefile(destination):
        destination.unlink()
    if not destination.exists():
        destination.hardlink_to(source)
    return sync_status(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--install", action="store_true")
    parser.add_argument("--destination", type=Path, default=default_destination())
    args = parser.parse_args()
    result = install(SOURCE, args.destination) if args.install else sync_status(SOURCE, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "current" else 1


if __name__ == "__main__":
    raise SystemExit(main())
