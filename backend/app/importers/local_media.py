"""Create local transcripts from every supported audio/video file in one folder."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .telegram_consultations import (
    DEFAULT_MODEL,
    OpenAITranscriber,
    _clean_transcript,
    _reject_repository_output,
    _sha256,
    _write_json,
)

MEDIA_SUFFIXES = {
    ".aac", ".aiff", ".avi", ".flac", ".m4a", ".m4v", ".mkv", ".mov", ".mp3", ".mp4",
    ".mpeg", ".mpg", ".ogg", ".opus", ".wav", ".webm", ".wma",
}
CHUNK_SECONDS = 20 * 60
TranscriptFunction = Callable[[Path], str]
PrepareAudioFunction = Callable[[Path, Path], list[Path]]


def _timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "media"
    return f"{hashlib.sha256(value.encode()).hexdigest()[:10]}-{readable}"


def _read_json(path: Path, fallback: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def _media_tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        packages = Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        candidates = sorted(packages.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe")) if packages.exists() else []
        if candidates:
            ffmpeg = str(candidates[-1])
            ffprobe = str(candidates[-1].with_name("ffprobe.exe"))
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and ffprobe must be installed to process local media")
    return ffmpeg, ffprobe


def _duration_seconds(path: Path) -> float | None:
    _, ffprobe = _media_tools()
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    value = json.loads(completed.stdout).get("format", {}).get("duration")
    return float(value) if value is not None else None


def _prepare_audio_chunks(source: Path, temporary: Path) -> list[Path]:
    ffmpeg, _ = _media_tools()
    chunks = temporary / "chunks"
    chunks.mkdir(parents=True)
    output_pattern = chunks / "part-%04d.mp3"
    subprocess.run(
        [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn",
            "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k", "-f", "segment",
            "-segment_time", str(CHUNK_SECONDS), "-reset_timestamps", "1", str(output_pattern),
        ],
        check=True, capture_output=True, text=True,
    )
    result = sorted(chunks.glob("part-*.mp3"))
    if not result:
        raise RuntimeError("FFmpeg did not produce an audio track")
    return result


def _render_timeline(files: list[dict[str, Any]]) -> str:
    lines = ["# Media timeline", ""]
    for item in sorted(files, key=lambda value: (value["date"], value["source_path"])):
        lines.append(f"## {item['date']} · {item['source_path']}")
        if item.get("transcript"):
            lines.extend((item["transcript"]["clean_transcript"], ""))
        else:
            lines.extend((f"[Транскрипция: {item.get('transcription_status', 'pending')}]", ""))
    return "\n".join(lines).rstrip() + "\n"


def _write_transcript(path: Path, item: dict[str, Any]) -> None:
    transcript = item.get("transcript")
    if not transcript:
        return
    path.write_text(
        f"# {item['source_path']}\n\nДата файла: {item['date']}\n\n"
        f"## Текст\n\n{transcript['clean_transcript']}\n\n"
        f"## Raw transcript\n\n{transcript['raw_transcript']}\n",
        encoding="utf-8",
    )


def import_media_folder(
    source: Path,
    output_root: Path,
    *,
    transcribe: TranscriptFunction | None = None,
    model: str = DEFAULT_MODEL,
    prepare_audio: PrepareAudioFunction = _prepare_audio_chunks,
) -> dict[str, Any]:
    """Transcribe supported files under `source`; preserve every source file read-only."""
    source, output_root = source.resolve(), output_root.resolve()
    if not source.is_dir():
        raise ValueError("source must be an existing folder")
    if output_root.is_relative_to(source):
        raise ValueError("output directory must be outside the source media folder")
    _reject_repository_output(output_root)
    package = output_root / f"media-{hashlib.sha256(str(source).encode()).hexdigest()[:12]}"
    transcripts = package / "transcripts"
    package.mkdir(parents=True, exist_ok=True)
    previous = _read_json(package / "media.json", [])
    by_path = {str(item["source_path"]): item for item in previous}
    candidates = sorted(
        (path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES),
        key=lambda path: path.as_posix(),
    )
    new_files = files_transcribed = 0

    def persist() -> None:
        _write_json(package / "media.json", sorted(by_path.values(), key=lambda item: (item["date"], item["source_path"])))

    for media in candidates:
        relative = media.relative_to(source).as_posix()
        old = by_path.get(relative)
        if not media.resolve().is_relative_to(source):
            by_path[relative] = {
                "source_path": relative,
                "date": datetime.fromtimestamp(media.lstat().st_mtime, tz=timezone.utc).isoformat(),
                "type": "unknown",
                "media_sha256": None,
                "media_duration_seconds": None,
                "transcription_status": "needs_review",
                "transcription_error": "media path resolves outside source folder",
            }
            persist()
            continue
        try:
            source_hash = _sha256(media)
            file_date = _timestamp(media)
        except OSError as exc:
            if old:
                old["media_read_error"] = f"cannot read media during this import: {exc}"
                by_path[relative] = old
            else:
                by_path[relative] = {
                    "source_path": relative, "date": datetime.now(tz=timezone.utc).isoformat(),
                    "type": "unknown", "media_sha256": None, "media_duration_seconds": None,
                    "transcription_status": "needs_review", "transcription_error": f"cannot read media: {exc}",
                }
            persist()
            continue
        if old and old.get("media_sha256") == source_hash and old.get("transcription_status") in {"success", "failed", "needs_review", "processing"}:
            if old["transcription_status"] == "processing":
                old["transcription_status"] = "needs_review"
                old["transcription_error"] = "previous transcription was interrupted; review before retry"
            by_path[relative] = old
            continue
        new_files += 1
        item: dict[str, Any] = {
            "source_path": relative, "date": file_date,
            "type": "video" if media.suffix.lower() in {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"} else "audio",
            "media_sha256": source_hash, "media_duration_seconds": None, "transcription_status": "pending",
        }
        by_path[relative] = item
        persist()
        try:
            item["media_duration_seconds"] = _duration_seconds(media)
        except Exception as exc:
            item["media_duration_error"] = str(exc)
        if transcribe is None:
            item["transcription_status"] = "failed"
            item["transcription_error"] = "OPENAI_API_KEY is not configured"
        else:
            item["transcription_status"] = "processing"
            by_path[relative] = item
            persist()
            try:
                with tempfile.TemporaryDirectory(prefix="local-media-transcription-") as temporary:
                    raw = "\n".join(transcribe(chunk) for chunk in prepare_audio(media, Path(temporary)))
                item["transcript"] = {"model": model, "raw_transcript": raw, "clean_transcript": _clean_transcript(raw)}
                item["transcription_status"] = "success"
                files_transcribed += 1
                transcripts.mkdir(parents=True, exist_ok=True)
                _write_transcript(transcripts / f"{_safe_name(relative)}.md", item)
            except Exception as exc:
                item["transcription_status"] = "failed"
                item["transcription_error"] = str(exc)
        by_path[relative] = item
        persist()

    files = sorted(by_path.values(), key=lambda item: (item["date"], item["source_path"]))
    timeline_path = package / "timeline.md"
    timeline_path.write_text(_render_timeline(files), encoding="utf-8")
    errors = [
        {"source_path": item["source_path"], "error": item.get("transcription_error") or item.get("transcription_status")}
        for item in files if item.get("transcription_status") != "success"
    ]
    summary = {
        "media_files": len(files), "new_files": new_files, "files_transcribed": files_transcribed,
        "files_success": sum(item.get("transcription_status") == "success" for item in files),
        "audio_duration_seconds": sum(item.get("media_duration_seconds") or 0 for item in files),
        "errors": errors, "timeline_path": str(timeline_path), "media_path": str(package / "media.json"),
    }
    _write_json(package / "import-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe all supported local audio/video files in a folder")
    parser.add_argument("source", type=Path, help="Folder with local media")
    parser.add_argument("--output", type=Path, required=True, help="Private directory for transcript results")
    parser.add_argument("--model", default=os.getenv("OPENAI_TRANSCRIPTION_MODEL", DEFAULT_MODEL))
    args = parser.parse_args()
    api_key = os.getenv("OPENAI_API_KEY")
    transcriber = OpenAITranscriber(api_key=api_key, model=args.model, language=os.getenv("OPENAI_TRANSCRIPTION_LANGUAGE", "ru")) if api_key else None
    print(json.dumps(import_media_folder(args.source, args.output, transcribe=transcriber, model=args.model), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
