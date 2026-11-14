#!/usr/bin/env python3
"""Build recovery archives on the server and verify their off-host copies."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path("/opt/edabalans")
STATE = Path("/var/lib/edabalans-site-recovery")
REVIEWS = Path("/srv/edabalans-public/reviews")
BUCKET = "s3://edabalans-postgres-backups-ajessi9majsb7glatojn/site-recovery"
INITIAL_SKILLS_SHA256 = "24847d17783af96dd99e2bc56ced36ecf3bca4affe4c6036b4ec197fd6cf1826"
SOURCES = (
    ".codex", ".github", "backend", "content", "docs", "infra", "prototypes",
    "telegram-bot", "tools", "compose.yaml", "AGENTS.md", "ARCHITECTURE.md",
    "PROJECT_CONTEXT.md", "README.md", ".env.example", ".gitattributes",
    ".gitignore", ".dockerignore", "work/calorie-course-rebuild/source-tilda/articles",
    "work/public-homepage-redesign",
)
MEDIA = "png jpg jpeg webp avif gif svg ico bmp tiff psd fig woff woff2 mp4 mov webm pdf zip"
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg", ".ico", ".bmp", ".tiff"}


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def validate_zip(path, required):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() or not all(name in archive.namelist() for name in required):
            raise RuntimeError(f"Invalid recovery archive: {path.name}")


def s3(work, *args):
    subprocess.run([
        "docker", "run", "--rm", "-e", "AWS_ACCESS_KEY_ID",
        "-e", "AWS_SECRET_ACCESS_KEY", "-e", "AWS_DEFAULT_REGION",
        "-v", f"{work}:/backup", "amazon/aws-cli:latest",
        "--endpoint-url", os.environ["S3_ENDPOINT"], "s3", "cp",
        *args, "--only-show-errors",
    ], check=True)


def publish(path, folder, work):
    checksum = digest(path)
    marker = STATE / f"{folder}.sha256"
    latest = STATE / f"{folder}-latest.zip"
    os.replace(path, latest)
    local_checksum = work / f"{latest.name}.sha256"
    local_checksum.write_text(f"{checksum}  {latest.name}\n", encoding="ascii")
    os.replace(local_checksum, STATE / local_checksum.name)
    if marker.exists() and marker.read_text().strip() == checksum:
        return
    remote = f"{BUCKET}/server/{folder}/{path.name}"
    sidecar = path.with_suffix(path.suffix + ".sha256")
    sidecar.write_text(f"{checksum}  {path.name}\n", encoding="ascii")
    os.link(latest, path)
    s3(work, f"/backup/{path.name}", remote)
    verification = work / "verification.zip"
    s3(work, remote, "/backup/verification.zip")
    if digest(verification) != checksum:
        raise RuntimeError("S3 verification checksum mismatch")
    verification.unlink()
    s3(work, f"/backup/{sidecar.name}", remote + ".sha256")
    marker.write_text(checksum + "\n", encoding="ascii")
    print(f"Verified {remote}", flush=True)


def site_archive(mode, work):
    commit = subprocess.check_output(["git", "-C", ROOT, "rev-parse", "HEAD"], text=True).strip()
    path = work / f"site-{mode}-{commit}.zip"
    excluded = [f":(exclude,glob,icase)**/*.{ext}" for ext in MEDIA.split()] if mode == "daily" else []
    subprocess.run([
        "git", "-C", ROOT, "archive", "--format=zip", f"--output={path}",
        commit, "--", *SOURCES, *excluded,
    ], check=True)
    validate_zip(path, ("ARCHITECTURE.md", "compose.yaml", "docs/OPERATIONS.md"))
    publish(path, mode, work)


def review_archive(work):
    files = sorted(
        path for path in REVIEWS.rglob("*")
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in IMAGES
    )
    if not files:
        raise RuntimeError("No production review images found")
    manifest = "".join(f"{digest(path)}  reviews/{path.relative_to(REVIEWS).as_posix()}\n" for path in files)
    fingerprint = hashlib.sha256(manifest.encode()).hexdigest()
    path = work / f"site-published-images-{fingerprint}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for image, row in zip(files, manifest.splitlines()):
            data = image.read_bytes()
            if hashlib.sha256(data).hexdigest() != row.split("  ", 1)[0]:
                raise RuntimeError("Production image changed during backup")
            entry = zipfile.ZipInfo("reviews/" + image.relative_to(REVIEWS).as_posix())
            archive.writestr(entry, data)
        archive.writestr(zipfile.ZipInfo("SHA256SUMS"), manifest)
    validate_zip(path, ("SHA256SUMS",))
    publish(path, "published-images", work)


def skills_archive(work):
    source = STATE / "inbox" / "codex-skills.zip"
    if not source.is_file():
        print("Seeding the server inbox from the verified initial skills snapshot", flush=True)
        seed = work / "codex-skills-seed.zip"
        s3(work, BUCKET + "/daily/codex-skills-2026-11-14.zip", "/backup/" + seed.name)
        if digest(seed) != INITIAL_SKILLS_SHA256:
            raise RuntimeError("Initial skills snapshot checksum mismatch")
        validate_zip(seed, ())
        os.replace(seed, source)
    temp = work / "skills-input.zip"
    shutil.copyfile(source, temp)
    validate_zip(temp, ())
    with zipfile.ZipFile(temp) as archive:
        if not any(name.endswith("/SKILL.md") for name in archive.namelist()):
            raise RuntimeError("Skills archive has no SKILL.md files")
    path = work / f"codex-skills-{digest(temp)}.zip"
    temp.rename(path)
    publish(path, "skills", work)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("daily", "weekly"))
    mode = parser.parse_args().mode
    for target, source in (
        ("AWS_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID"),
        ("AWS_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY"),
        ("AWS_DEFAULT_REGION", "S3_REGION"),
    ):
        os.environ[target] = os.environ[source]
    STATE.mkdir(mode=0o700, exist_ok=True)
    (STATE / "inbox").mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="build-", dir=STATE) as directory:
        work = Path(directory)
        site_archive(mode, work)
        if mode == "daily":
            skills_archive(work)
        else:
            review_archive(work)


if __name__ == "__main__":
    main()
