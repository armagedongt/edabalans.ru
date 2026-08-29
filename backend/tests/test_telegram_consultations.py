import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest

from app.importers.telegram_consultations import OpenAITranscriber, import_export


def make_export(root: Path) -> Path:
    export = root / "export"
    voice = export / "voice_messages" / "voice.ogg"
    voice.parent.mkdir(parents=True)
    voice.write_bytes(b"test audio")
    payload = {
        "name": "Test chat", "type": "personal_chat", "id": 777,
        "messages": [
            {"id": 3, "type": "message", "date_unixtime": "1700000003", "from": "Client", "text": "After voice"},
            {"id": 1, "type": "message", "date_unixtime": "1700000001", "from": "Coach", "text": "Before voice"},
            {"id": 2, "type": "message", "date_unixtime": "1700000002", "from": "Client", "media_type": "voice_message", "file": "voice_messages/voice.ogg", "mime_type": "audio/ogg", "duration_seconds": 42, "text": ""},
        ],
    }
    (export / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    return export


def test_imports_folder_voice_and_timeline_in_chronological_order(tmp_path: Path) -> None:
    calls: list[Path] = []

    def transcribe(path: Path) -> str:
        calls.append(path)
        return "  сырая   расшифровка  "

    export = make_export(tmp_path)
    source_audio = export / "voice_messages" / "voice.ogg"
    source_before = source_audio.read_bytes()
    summary = import_export(export, tmp_path / "private", transcribe=transcribe)

    assert summary["messages"] == 3
    assert summary["voices"] == 1
    assert summary["audio_duration_seconds"] == 42
    assert summary["voices_success"] == 1
    assert len(calls) == 1
    package = Path(summary["client_path"]).parent
    messages = json.loads((package / "messages.json").read_text(encoding="utf-8"))
    voice = next(item for item in messages if item["message_id"] == 2)
    assert {"chat_id", "message_id", "date", "author", "type", "media_path"} <= set(voice)
    assert voice["media_sha256"] == hashlib.sha256(source_before).hexdigest()
    assert voice["transcript"]["raw_transcript"] == "  сырая   расшифровка  "
    assert voice["transcript"]["clean_transcript"] == "сырая расшифровка"
    timeline = Path(summary["timeline_path"]).read_text(encoding="utf-8")
    assert timeline.index("Before voice") < timeline.index("Голосовое") < timeline.index("After voice")
    assert source_audio.read_bytes() == source_before
    client = json.loads(Path(summary["client_path"]).read_text(encoding="utf-8"))
    assert client["message_count"] == 3
    assert client["voice_count"] == 1
    assert client["audio_duration_seconds"] == 42
    assert client["timeline_path"] == summary["timeline_path"]


def test_reimport_from_zip_does_not_duplicate_or_retranscribe(tmp_path: Path) -> None:
    export = make_export(tmp_path)
    archive = tmp_path / "telegram.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in export.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(export))
    archive_before = archive.read_bytes()
    calls: list[Path] = []

    def transcribe(path: Path) -> str:
        calls.append(path)
        return "готово"

    output = tmp_path / "private"
    first = import_export(archive, output, transcribe=transcribe)
    second = import_export(archive, output, transcribe=transcribe)

    assert first["new_messages"] == 3
    assert second["new_messages"] == 0
    assert second["voices_transcribed"] == 0
    assert second["voices_success"] == 1
    assert len(calls) == 1
    assert archive.read_bytes() == archive_before


def test_changed_voice_with_same_message_id_is_retranscribed(tmp_path: Path) -> None:
    export = make_export(tmp_path)
    output = tmp_path / "private"
    calls: list[bytes] = []

    def transcribe(path: Path) -> str:
        calls.append(path.read_bytes())
        return f"version {len(calls)}"

    import_export(export, output, transcribe=transcribe)
    (export / "voice_messages" / "voice.ogg").write_bytes(b"replacement audio")
    summary = import_export(export, output, transcribe=transcribe)

    messages = json.loads((Path(summary["client_path"]).parent / "messages.json").read_text(encoding="utf-8"))
    voice = next(item for item in messages if item["message_id"] == 2)
    assert calls == [b"test audio", b"replacement audio"]
    assert voice["transcript"]["clean_transcript"] == "version 2"
    assert voice["media_sha256"] == hashlib.sha256(b"replacement audio").hexdigest()


def test_rejects_result_directory_inside_folder_export(tmp_path: Path) -> None:
    export = make_export(tmp_path)

    try:
        import_export(export, export / "results", transcribe=lambda _: "unused")
    except ValueError as exc:
        assert "outside the source export" in str(exc)
    else:
        raise AssertionError("output inside source export must be rejected")


def test_rejects_private_output_inside_git_repository(tmp_path: Path) -> None:
    export = make_export(tmp_path)
    repository = tmp_path / "repository"
    (repository / ".git").mkdir(parents=True)

    try:
        import_export(export, repository / "private", transcribe=lambda _: "unused")
    except ValueError as exc:
        assert "outside a Git repository" in str(exc)
    else:
        raise AssertionError("private output inside a Git repository must be rejected")


def test_media_symlink_outside_export_is_not_transcribed(tmp_path: Path) -> None:
    export = make_export(tmp_path)
    outside = tmp_path / "outside.ogg"
    outside.write_bytes(b"private outside audio")
    linked = export / "voice_messages" / "voice.ogg"
    linked.unlink()
    try:
        os.symlink(outside, linked)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")
    calls: list[Path] = []

    summary = import_export(export, tmp_path / "private", transcribe=lambda path: calls.append(path) or "must not run")

    assert calls == []
    assert summary["voices_success"] == 0
    assert "outside export" in summary["errors"][0]["error"]


def test_formatted_telegram_text_is_flattened_in_order(tmp_path: Path) -> None:
    export = make_export(tmp_path)
    result = export / "result.json"
    payload = json.loads(result.read_text(encoding="utf-8"))
    payload["messages"][0]["text"] = ["До ", {"type": "bold", "text": "ссылки"}, " после"]
    result.write_text(json.dumps(payload), encoding="utf-8")

    summary = import_export(export, tmp_path / "private", transcribe=lambda _: "voice")
    messages = json.loads((Path(summary["client_path"]).parent / "messages.json").read_text(encoding="utf-8"))

    assert next(item for item in messages if item["message_id"] == 3)["text"] == "До ссылки после"


def test_zip_path_traversal_is_rejected_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("result.json", json.dumps({"id": 1, "messages": []}))
        bundle.writestr("../outside.txt", "must not be extracted")

    with pytest.raises(ValueError, match="unsafe file path"):
        import_export(archive, tmp_path / "private")

    assert not (tmp_path / "outside.txt").exists()


def test_openai_transcriber_builds_expected_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"audio bytes")
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self) -> bytes:
            return b'{"text":"ready"}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = OpenAITranscriber(api_key="test-key", model="test-model", language="ru")(audio)

    request = captured["request"]
    assert result == "ready"
    assert request.full_url == "https://api.openai.com/v1/audio/transcriptions"
    assert request.get_header("Authorization") == "Bearer test-key"
    assert request.get_header("Content-type").startswith("multipart/form-data; boundary=")
    assert b'name="model"\r\n\r\ntest-model' in request.data
    assert b'name="language"\r\n\r\nru' in request.data
    assert b"audio bytes" in request.data
    assert captured["timeout"] == 300


def test_one_failed_voice_does_not_stop_later_voice(tmp_path: Path) -> None:
    export = make_export(tmp_path)
    second_audio = export / "voice_messages" / "second.ogg"
    second_audio.write_bytes(b"second test audio")
    result_path = export / "result.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["messages"].extend([
        {"id": 4, "type": "message", "date_unixtime": "1700000004", "from": "Client", "media_type": "voice_message", "file": "voice_messages/second.ogg", "mime_type": "audio/ogg", "duration_seconds": 5, "text": ""},
        {"id": 5, "type": "message", "date_unixtime": "1700000005", "from": "Coach", "text": "Still here"},
    ])
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    def transcribe(path: Path) -> str:
        if path.name == "voice.ogg":
            raise RuntimeError("bad audio")
        return "second transcript"

    summary = import_export(export, tmp_path / "private", transcribe=transcribe)
    messages = json.loads((Path(summary["client_path"]).parent / "messages.json").read_text(encoding="utf-8"))
    failed = next(item for item in messages if item["message_id"] == 2)
    succeeded = next(item for item in messages if item["message_id"] == 4)
    assert failed["voice_status"] == "failed"
    assert succeeded["voice_status"] == "success"
    assert summary["voices_success"] == 1
    assert summary["errors"] == [{"message_id": 2, "error": "bad audio"}]
    assert "Still here" in Path(summary["timeline_path"]).read_text(encoding="utf-8")
    second = import_export(export, tmp_path / "private", transcribe=lambda _: (_ for _ in ()).throw(AssertionError("must not retry")))
    assert second["voices_transcribed"] == 0
    assert second["voices_success"] == 1
    assert second["errors"] == [{"message_id": 2, "error": "bad audio"}]
