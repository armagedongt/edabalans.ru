"""Create and restore an encrypted backup of the private author-memory corpus."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tarfile
import tempfile
from typing import Iterable

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
except ImportError:  # pragma: no cover - depends on the caller's runtime
    AESGCM = None
    InvalidTag = Exception


MAGIC = b"EDABALANS-AUTHOR-MEMORY\x00\x01"
AAD = b"edabalans-author-memory-backup-v1"
NONCE_SIZE = 12
KEY_SIZE = 32


def restrict_private_file(path: Path) -> None:
    """Keep backup keys and ciphertext private on POSIX and Windows."""
    os.chmod(path, 0o600)
    if os.name != "nt":
        return
    try:
        identity = subprocess.run(
            ["whoami"],
            check=True,
            capture_output=True,
            text=True,
        )
        account = identity.stdout.strip()
        if not account:
            raise RuntimeError("cannot determine the Windows account for backup ACL")
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{account}:(F)",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"cannot restrict Windows ACL for {path}") from exc


def require_crypto() -> None:
    if AESGCM is None:
        raise RuntimeError(
            "backup_author_memory.py requires the 'cryptography' package. "
            "Use the bundled Codex workspace Python or install cryptography."
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_source(value: str) -> tuple[str, Path]:
    label, separator, raw_path = value.partition("=")
    if not separator or not label.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("source must use LABEL=PATH")
    label = label.strip()
    if "/" in label or "\\" in label or label in {".", ".."}:
        raise argparse.ArgumentTypeError("source label must be one safe path segment")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"source directory does not exist: {path}")
    return label, path


def iter_source_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            continue
        if path.is_file():
            yield path


def load_existing_key(path: Path) -> bytes:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"backup key file is missing: {path}")
    restrict_private_file(path)
    try:
        key = base64.urlsafe_b64decode(path.read_text(encoding="ascii").strip())
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"invalid backup key file: {path}") from exc
    if len(key) != KEY_SIZE:
        raise ValueError(f"backup key must decode to {KEY_SIZE} bytes")
    return key


def load_or_create_key(path: Path) -> bytes:
    path = path.expanduser().resolve()
    if path.exists():
        return load_existing_key(path)

    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(KEY_SIZE)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="ascii")
    try:
        restrict_private_file(temporary)
        temporary.replace(path)
        restrict_private_file(path)
    finally:
        temporary.unlink(missing_ok=True)
    return key


def build_plain_archive(sources: list[tuple[str, Path]], destination: Path) -> dict:
    manifest: dict = {
        "format": "edabalans-author-memory-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sources": [],
        "files": [],
    }
    seen_labels: set[str] = set()

    with tarfile.open(destination, "w:gz") as archive:
        for label, root in sources:
            if label in seen_labels:
                raise ValueError(f"duplicate source label: {label}")
            seen_labels.add(label)
            source_count = 0
            source_bytes = 0
            for path in iter_source_files(root):
                relative = path.relative_to(root).as_posix()
                archive_name = f"sources/{label}/{relative}"
                size = path.stat().st_size
                digest = sha256_file(path)
                archive.add(path, arcname=archive_name, recursive=False)
                manifest["files"].append(
                    {"path": archive_name, "size": size, "sha256": digest}
                )
                source_count += 1
                source_bytes += size
            manifest["sources"].append(
                {"label": label, "files": source_count, "bytes": source_bytes}
            )

        payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        info.mtime = int(datetime.now(timezone.utc).timestamp())
        with tempfile.SpooledTemporaryFile() as handle:
            handle.write(payload)
            handle.seek(0)
            archive.addfile(info, handle)
    return manifest


def encrypt_archive(plain: Path, encrypted: Path, key: bytes) -> None:
    require_crypto()
    nonce = secrets.token_bytes(NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plain.read_bytes(), AAD)
    temporary = encrypted.with_suffix(encrypted.suffix + ".tmp")
    try:
        temporary.write_bytes(MAGIC + nonce + ciphertext)
        temporary.replace(encrypted)
        restrict_private_file(encrypted)
    finally:
        temporary.unlink(missing_ok=True)


def decrypt_archive(encrypted: Path, plain: Path, key: bytes) -> None:
    require_crypto()
    payload = encrypted.read_bytes()
    prefix_size = len(MAGIC) + NONCE_SIZE
    if len(payload) <= prefix_size or not payload.startswith(MAGIC):
        raise ValueError("not an edabalans author-memory backup")
    nonce = payload[len(MAGIC):prefix_size]
    ciphertext = payload[prefix_size:]
    try:
        cleartext = AESGCM(key).decrypt(nonce, ciphertext, AAD)
    except InvalidTag as exc:
        raise ValueError("backup authentication failed: wrong key or damaged archive") from exc
    plain.write_bytes(cleartext)


def safe_extract(archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"unsupported archive entry: {member.name}")
            target = (destination / member.name).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError(f"unsafe archive entry: {member.name}")
        archive.extractall(destination, filter="data")


def create_backup(
    sources: list[tuple[str, Path]], output_dir: Path, key_file: Path,
    timestamp: str | None = None,
) -> dict:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    key = load_or_create_key(key_file)
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    encrypted = output_dir / f"author-memory-{stamp}.tar.gz.aes256"
    if encrypted.exists():
        raise FileExistsError(encrypted)

    with tempfile.TemporaryDirectory(prefix="author-memory-backup-") as folder:
        plain = Path(folder) / "author-memory.tar.gz"
        manifest = build_plain_archive(sources, plain)
        encrypt_archive(plain, encrypted, key)

    checksum = encrypted.with_suffix(encrypted.suffix + ".sha256")
    checksum.write_text(f"{sha256_file(encrypted)}  {encrypted.name}\n", encoding="ascii")
    restrict_private_file(checksum)
    metadata = encrypted.with_suffix(encrypted.suffix + ".json")
    metadata.write_text(
        json.dumps(
            {
                "format": manifest["format"],
                "created_at": manifest["created_at"],
                "archive": encrypted.name,
                "sha256": sha256_file(encrypted),
                "sources": manifest["sources"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    restrict_private_file(metadata)
    return {
        "archive": str(encrypted),
        "checksum": str(checksum),
        "metadata": str(metadata),
        "sources": manifest["sources"],
    }


def restore_backup(archive: Path, key_file: Path, output_dir: Path) -> dict:
    archive = archive.expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    key = load_existing_key(key_file)
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"restore directory must be empty: {output_dir}")

    with tempfile.TemporaryDirectory(prefix="author-memory-restore-") as folder:
        plain = Path(folder) / "author-memory.tar.gz"
        decrypt_archive(archive, plain, key)
        safe_extract(plain, output_dir)

    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        path = output_dir / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["size"]:
            raise ValueError(f"restored file is missing or truncated: {entry['path']}")
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"restored checksum mismatch: {entry['path']}")
    return {"status": "restored", "files": len(manifest["files"]), "output": str(output_dir)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="create an encrypted backup")
    create.add_argument("--source", action="append", type=parse_source, required=True)
    create.add_argument("--output-dir", type=Path, required=True)
    create.add_argument("--key-file", type=Path, required=True)

    restore = subparsers.add_parser("restore", help="decrypt, extract and verify a backup")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--key-file", type=Path, required=True)
    restore.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "create":
        result = create_backup(args.source, args.output_dir, args.key_file)
    else:
        result = restore_backup(args.archive, args.key_file, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
