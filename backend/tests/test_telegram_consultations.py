import hashlib
import json
import zipfile
from pathlib import Path

from app.importers.telegram_consultations import import_export


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


def test_rejects_result_directory_inside_folder_export(tmp_path: Path) -> None:
    export = make_export(tmp_path)

    try:
        import_export(export, export / "results", transcribe=lambda _: "unused")
    except ValueError as exc:
        assert "outside the source export" in str(exc)
    else:
        raise AssertionError("output inside source export must be rejected")


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
