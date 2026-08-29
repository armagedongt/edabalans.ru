"""Import a Telegram Desktop conversation export into a local transcript package."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import tempfile
import urllib.error
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PARSER_VERSION = "telegram-consultation-export-v1"
DEFAULT_MODEL = "gpt-4o-mini-transcribe"
VOICE_MEDIA_TYPES = {"voice_message", "voice", "audio_message"}
TranscriptFunction = Callable[[Path], str]


def flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(item if isinstance(item, str) else str(item.get("text") or "") for item in value if isinstance(item, (str, dict)))
    return ""


def _utc_timestamp(message: dict[str, Any]) -> str:
    raw = message.get("date_unixtime")
    if raw not in (None, ""):
        return datetime.fromtimestamp(int(raw), tz=timezone.utc).isoformat()
    value = str(message.get("date") or "")
    if not value:
        raise ValueError(f"message {message.get('id')!r} has no date")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).isoformat()


def _safe_relative_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value or value.startswith("(File not included"):
        return None
    candidate = Path(value.replace("\\", "/"))
    return None if candidate.is_absolute() or ".." in candidate.parts else candidate


def _media_path(message: dict[str, Any]) -> Path | None:
    return _safe_relative_path(message.get("file") or message.get("photo"))


def _is_voice(message: dict[str, Any]) -> bool:
    return str(message.get("media_type") or "").lower() in VOICE_MEDIA_TYPES or str(message.get("mime_type") or "").lower().startswith("audio/")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_transcript(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _read_json(path: Path, fallback: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _reject_repository_output(output_root: Path) -> None:
    """Keep private import packages outside every Git working tree."""
    for candidate in (output_root, *output_root.parents):
        if (candidate / ".git").exists():
            raise ValueError("output directory must be outside a Git repository")


def _find_result_json(root: Path) -> Path:
    matches = list(root.rglob("result.json"))
    if len(matches) != 1:
        raise ValueError("archive or folder must contain exactly one result.json")
    return matches[0]


def _extract_zip(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source) as archive:
        base = destination.resolve()
        if len(archive.infolist()) > 50_000 or sum(member.file_size for member in archive.infolist()) > 4 * 1024**3:
            raise ValueError("archive is too large to extract safely")
        for member in archive.infolist():
            if not (destination / member.filename).resolve().is_relative_to(base):
                raise ValueError("archive contains an unsafe file path")
        archive.extractall(destination)


def _source_root(source: Path, temporary_root: Path) -> Path:
    if source.is_dir():
        return source
    if source.suffix.lower() != ".zip":
        raise ValueError("source must be a Telegram export folder or a ZIP archive")
    _extract_zip(source, temporary_root)
    return temporary_root


def _multipart_request(audio_path: Path, model: str, language: str | None) -> tuple[str, bytes]:
    boundary = f"----telegram-import-{uuid.uuid4().hex}"
    mime_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    parts: list[bytes] = []
    for name, value in (("model", model), ("language", language)):
        if value:
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{audio_path.name}\"\r\nContent-Type: {mime_type}\r\n\r\n".encode())
    parts.extend((audio_path.read_bytes(), f"\r\n--{boundary}--\r\n".encode()))
    return boundary, b"".join(parts)


class OpenAITranscriber:
    def __init__(self, *, api_key: str, model: str, language: str | None) -> None:
        self.api_key, self.model, self.language = api_key, model, language

    def __call__(self, audio_path: Path) -> str:
        boundary, body = _multipart_request(audio_path, self.model, self.language)
        request = urllib.request.Request(
            "https://api.openai.com/v1/audio/transcriptions", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"OpenAI transcription failed ({exc.code}): {exc.read().decode('utf-8', errors='replace')[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI transcription connection failed: {exc.reason}") from exc
        if not isinstance(payload.get("text"), str):
            raise RuntimeError("OpenAI transcription response did not contain text")
        return payload["text"]


def _normalise_messages(payload: dict[str, Any], source_root: Path) -> list[dict[str, Any]]:
    chat_id = str(payload.get("id") or "")
    if not chat_id or not isinstance(payload.get("messages"), list):
        raise ValueError("result.json must contain chat id and messages")
    normalized, seen = [], set()
    for raw in payload["messages"]:
        if not isinstance(raw, dict) or raw.get("type") != "message":
            continue
        message_id = int(raw["id"])
        if message_id in seen:
            raise ValueError(f"duplicate message id {message_id} in result.json")
        seen.add(message_id)
        relative = _media_path(raw)
        candidate = source_root / relative if relative else None
        path_is_safe = bool(candidate and candidate.resolve().is_relative_to(source_root.resolve()))
        audio = candidate if path_is_safe else None
        exists = bool(audio and audio.is_file())
        media_sha256 = None
        media_read_error = None
        if exists and audio:
            try:
                media_sha256 = _sha256(audio)
            except OSError as exc:
                media_read_error = str(exc)
        voice = _is_voice(raw)
        normalized.append({
            "chat_id": chat_id, "message_id": message_id, "date": _utc_timestamp(raw),
            "author": raw.get("from") or raw.get("author") or "", "author_id": raw.get("from_id"),
            "type": "voice" if voice else str(raw.get("media_type") or "text"), "text": flatten_text(raw.get("text")),
            "media_path": relative.as_posix() if relative else None, "media_sha256": media_sha256,
            "media_duration_seconds": raw.get("duration_seconds") or raw.get("duration"), "voice": voice,
            "media_missing": bool(relative and not exists), "media_path_unsafe": bool(relative and not path_is_safe), "media_read_error": media_read_error,
        })
    return sorted(normalized, key=lambda item: (item["date"], item["message_id"]))


def _render_timeline(messages: list[dict[str, Any]]) -> str:
    lines = ["# Telegram timeline", ""]
    for message in sorted(messages, key=lambda item: (item["date"], item["message_id"])):
        lines.append(f"## {message['date']} · {message['author'] or 'Unknown'} · #{message['message_id']}")
        if message["text"]:
            lines.extend((message["text"], ""))
        if message.get("transcript"):
            transcript = message["transcript"]
            lines.extend((f"**Голосовое:** {transcript.get('clean_transcript') or transcript.get('raw_transcript') or ''}", ""))
        elif message["voice"]:
            lines.extend((f"**Голосовое:** [{message.get('voice_status', 'pending')}]", ""))
    return "\n".join(lines).rstrip() + "\n"


def import_export(source: Path, output_root: Path, *, transcribe: TranscriptFunction | None = None, model: str = DEFAULT_MODEL, language: str | None = "ru") -> dict[str, Any]:
    """Import a folder/ZIP. `transcribe` is injectable so tests never call OpenAI."""
    source, output_root = source.resolve(), output_root.resolve()
    if not source.exists():
        raise ValueError(f"source does not exist: {source}")
    if source.is_dir() and output_root.is_relative_to(source):
        raise ValueError("output directory must be outside the source export")
    _reject_repository_output(output_root)
    with tempfile.TemporaryDirectory(prefix="telegram-consultation-") as temporary:
        source_root = _source_root(source, Path(temporary))
        result_path = _find_result_json(source_root)
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        messages, chat_id = _normalise_messages(payload, result_path.parent), str(payload["id"])
        package = output_root / f"chat-{re.sub(r'[^A-Za-z0-9_-]+', '_', chat_id)}"
        package.mkdir(parents=True, exist_ok=True)
        previous = _read_json(package / "messages.json", [])
        by_key = {(str(item["chat_id"]), int(item["message_id"])): item for item in previous}
        errors, new_messages, voices_transcribed = [], 0, 0

        def persist_progress() -> None:
            _write_json(package / "messages.json", sorted(by_key.values(), key=lambda item: (item["date"], item["message_id"])))

        for message in messages:
            key = (message["chat_id"], message["message_id"])
            old = by_key.get(key)
            same_media = bool(old and old.get("media_sha256") == message.get("media_sha256"))
            if old and (not message["voice"] or same_media):
                message["transcript"], message["voice_status"] = old.get("transcript"), old.get("voice_status")
                message["voice_error"] = old.get("voice_error")
            else:
                new_messages += 1
            if not message["voice"]:
                by_key[key] = message
                continue
            if old and same_media and message.get("voice_status") in {"success", "failed", "needs_review", "processing"}:
                if message["voice_status"] == "processing":
                    message["voice_status"] = "needs_review"
                    message["voice_error"] = "previous transcription was interrupted; review before retry"
                by_key[key] = message
                continue
            message["voice_status"] = "pending"
            by_key[key] = message
            persist_progress()
            relative = _safe_relative_path(message["media_path"])
            audio = result_path.parent / relative if relative else None
            if message.get("media_path_unsafe"):
                message["voice_status"] = "needs_review"; message["voice_error"] = "media path resolves outside export"
            elif message.get("media_read_error"):
                message["voice_status"] = "needs_review"; message["voice_error"] = f"cannot read media: {message['media_read_error']}"
            elif not audio or not audio.is_file():
                message["voice_status"] = "needs_review"; message["voice_error"] = "voice file is missing from export"
            elif transcribe is None:
                message["voice_status"] = "failed"; message["voice_error"] = "OPENAI_API_KEY is not configured"
            else:
                message["voice_status"] = "processing"
                by_key[key] = message
                persist_progress()
                try:
                    raw = transcribe(audio)
                    message["transcript"] = {"model": model, "raw_transcript": raw, "clean_transcript": _clean_transcript(raw)}
                    message["voice_status"] = "success"; voices_transcribed += 1
                except Exception as exc:
                    message["voice_status"] = "failed"; message["voice_error"] = str(exc)
            by_key[key] = message
            persist_progress()
        all_messages = sorted(by_key.values(), key=lambda item: (item["date"], item["message_id"]))
        timeline_path = package / "timeline.md"
        _write_json(package / "messages.json", all_messages)
        timeline_path.write_text(_render_timeline(all_messages), encoding="utf-8")
        voices = [item for item in all_messages if item["voice"]]
        errors = [
            {"message_id": item["message_id"], "error": item.get("voice_error") or item.get("voice_status")}
            for item in voices
            if item.get("voice_status") != "success"
        ]
        client = {"schema_version": 1, "parser_version": PARSER_VERSION, "chat_id": chat_id, "chat_name": payload.get("name"), "source_type": payload.get("type"), "imported_at": datetime.now(tz=timezone.utc).isoformat(), "message_count": len(all_messages), "voice_count": len(voices), "audio_duration_seconds": sum(int(item.get("media_duration_seconds") or 0) for item in voices), "timeline_path": str(timeline_path)}
        _write_json(package / "client.json", client)
        summary = {"messages": len(all_messages), "new_messages": new_messages, "voices": len(voices), "audio_duration_seconds": client["audio_duration_seconds"], "voices_transcribed": voices_transcribed, "voices_success": sum(item.get("voice_status") == "success" for item in voices), "errors": errors, "timeline_path": str(timeline_path), "client_path": str(package / "client.json")}
        _write_json(package / "import-summary.json", summary)
        return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a Telegram Desktop conversation export")
    parser.add_argument("source", type=Path, help="Telegram export ZIP or folder")
    parser.add_argument("--output", type=Path, required=True, help="Private directory for import results")
    parser.add_argument("--model", default=os.getenv("OPENAI_TRANSCRIPTION_MODEL", DEFAULT_MODEL))
    parser.add_argument("--language", default=os.getenv("OPENAI_TRANSCRIPTION_LANGUAGE", "ru"))
    args = parser.parse_args()
    api_key = os.getenv("OPENAI_API_KEY")
    transcriber = OpenAITranscriber(api_key=api_key, model=args.model, language=args.language) if api_key else None
    print(json.dumps(import_export(args.source, args.output, transcribe=transcriber, model=args.model, language=args.language), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
