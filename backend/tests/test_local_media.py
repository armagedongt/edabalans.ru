import hashlib
import json
import os
from pathlib import Path

import pytest

from app.importers import local_media
from app.importers.local_media import _prepare_audio_chunks, _safe_name, import_media_folder


def test_folder_media_is_transcribed_and_source_is_not_modified(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    first, second = media / "first.mp4", media / "nested" / "second.m4a"
    second.parent.mkdir()
    first.write_bytes(b"video source")
    second.write_bytes(b"audio source")
    calls: list[str] = []

    def transcribe(chunk: Path) -> str:
        calls.append(chunk.name)
        return f"raw {chunk.name}"

    def prepare(source: Path, temporary: Path) -> list[Path]:
        chunk = temporary / f"{source.stem}.mp3"
        chunk.write_bytes(b"temporary audio")
        return [chunk]

    before = {path: path.read_bytes() for path in (first, second)}
    summary = import_media_folder(media, tmp_path / "results", transcribe=transcribe, prepare_audio=prepare)

    assert summary["media_files"] == 2
    assert summary["files_success"] == 2
    assert len(calls) == 2
    assert {path: path.read_bytes() for path in (first, second)} == before
    package = Path(summary["media_path"]).parent
    files = json.loads((package / "media.json").read_text(encoding="utf-8"))
    assert {item["source_path"] for item in files} == {"first.mp4", "nested/second.m4a"}
    assert next(item for item in files if item["source_path"] == "first.mp4")["media_sha256"] == hashlib.sha256(b"video source").hexdigest()
    assert (package / "transcripts" / f"{_safe_name('first.mp4')}.md").exists()
    assert "raw first.mp3" in Path(summary["timeline_path"]).read_text(encoding="utf-8")


def test_repeat_does_not_transcribe_unchanged_media(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "voice.ogg").write_bytes(b"voice")
    calls: list[str] = []

    def transcribe(chunk: Path) -> str:
        calls.append(chunk.name)
        return "done"

    def prepare(source: Path, temporary: Path) -> list[Path]:
        return [source]

    output = tmp_path / "results"
    import_media_folder(media, output, transcribe=transcribe, prepare_audio=prepare)
    second = import_media_folder(media, output, transcribe=transcribe, prepare_audio=prepare)

    assert len(calls) == 1
    assert second["new_files"] == 0
    assert second["files_transcribed"] == 0


def test_replaced_media_with_same_path_is_retranscribed(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    source = media / "voice.ogg"
    source.write_bytes(b"first voice")
    calls: list[bytes] = []

    def transcribe(chunk: Path) -> str:
        calls.append(chunk.read_bytes())
        return f"version {len(calls)}"

    output = tmp_path / "results"
    import_media_folder(media, output, transcribe=transcribe, prepare_audio=lambda path, _: [path])
    source.write_bytes(b"replacement voice")
    summary = import_media_folder(media, output, transcribe=transcribe, prepare_audio=lambda path, _: [path])
    record = json.loads(Path(summary["media_path"]).read_text(encoding="utf-8"))[0]

    assert calls == [b"first voice", b"replacement voice"]
    assert record["transcript"]["clean_transcript"] == "version 2"
    assert record["media_sha256"] == hashlib.sha256(b"replacement voice").hexdigest()


def test_interrupted_media_is_marked_for_review_without_retry(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    source = media / "voice.ogg"
    source.write_bytes(b"voice")
    output = tmp_path / "results"
    first = import_media_folder(media, output, transcribe=lambda _: "first transcript", prepare_audio=lambda path, _: [path])
    media_path = Path(first["media_path"])
    records = json.loads(media_path.read_text(encoding="utf-8"))
    records[0]["transcription_status"] = "processing"
    records[0]["transcript"] = None
    media_path.write_text(json.dumps(records), encoding="utf-8")
    calls: list[Path] = []

    second = import_media_folder(
        media,
        output,
        transcribe=lambda path: calls.append(path) or "must not run",
        prepare_audio=lambda path, _: [path],
    )
    updated = json.loads(media_path.read_text(encoding="utf-8"))[0]

    assert calls == []
    assert updated["transcription_status"] == "needs_review"
    assert "interrupted" in updated["transcription_error"]
    assert second["files_transcribed"] == 0


def test_multiple_chunks_are_transcribed_and_joined_in_order(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    source = media / "long.mp4"
    source.write_bytes(b"long video")

    def prepare(_: Path, temporary: Path) -> list[Path]:
        first, second = temporary / "part-0000.mp3", temporary / "part-0001.mp3"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        return [first, second]

    summary = import_media_folder(media, tmp_path / "results", transcribe=lambda chunk: chunk.read_text() if False else chunk.stem, prepare_audio=prepare)
    record = json.loads(Path(summary["media_path"]).read_text(encoding="utf-8"))[0]

    assert record["transcript"]["raw_transcript"] == "part-0000\npart-0001"


def test_result_directory_inside_source_is_rejected(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    try:
        import_media_folder(media, media / "results")
    except ValueError as exc:
        assert "outside the source media folder" in str(exc)
    else:
        raise AssertionError("result directory inside source must be rejected")


def test_result_directory_inside_git_repository_is_rejected(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    repository = tmp_path / "repository"
    (repository / ".git").mkdir(parents=True)

    try:
        import_media_folder(media, repository / "private")
    except ValueError as exc:
        assert "outside a Git repository" in str(exc)
    else:
        raise AssertionError("private output inside a Git repository must be rejected")


def test_symlink_outside_source_is_not_read_or_transcribed(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"private outside audio")
    linked = media / "linked.mp3"
    try:
        os.symlink(outside, linked)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")
    calls: list[Path] = []

    summary = import_media_folder(
        media,
        tmp_path / "results",
        transcribe=lambda path: calls.append(path) or "must not run",
        prepare_audio=lambda source, _: [source],
    )

    assert calls == []
    assert summary["files_success"] == 0
    assert summary["errors"] == [{"source_path": "linked.mp3", "error": "media path resolves outside source folder"}]


def test_resolved_media_outside_source_is_rejected_before_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    linked = media / "linked.mp3"
    linked.write_bytes(b"placeholder")
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"private outside audio")
    original_resolve = Path.resolve

    def fake_resolve(path: Path, *args, **kwargs) -> Path:
        if path == linked:
            return outside
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    calls: list[Path] = []

    summary = import_media_folder(
        media,
        tmp_path / "results",
        transcribe=lambda path: calls.append(path) or "must not run",
        prepare_audio=lambda source, _: [source],
    )

    assert calls == []
    assert summary["files_success"] == 0
    assert summary["errors"] == [{"source_path": "linked.mp3", "error": "media path resolves outside source folder"}]


def test_prepare_audio_chunks_uses_segmented_ffmpeg_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        chunks = tmp_path / "temporary" / "chunks"
        chunks.mkdir(parents=True, exist_ok=True)
        (chunks / "part-0000.mp3").write_bytes(b"first")
        (chunks / "part-0001.mp3").write_bytes(b"second")

    monkeypatch.setattr(local_media, "_media_tools", lambda: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr(local_media.subprocess, "run", fake_run)

    result = _prepare_audio_chunks(source, tmp_path / "temporary")

    assert [path.name for path in result] == ["part-0000.mp3", "part-0001.mp3"]
    assert commands[0][0] == "ffmpeg"
    assert commands[0][commands[0].index("-segment_time") + 1] == str(local_media.CHUNK_SECONDS)
    assert "-vn" in commands[0]
    assert commands[0][-1].endswith("part-%04d.mp3")


def test_one_failed_file_does_not_stop_later_file(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "broken.mp3").write_bytes(b"broken")
    (media / "good.mp3").write_bytes(b"good")

    def transcribe(chunk: Path) -> str:
        if chunk.name == "broken.mp3":
            raise RuntimeError("bad file")
        return "good transcript"

    summary = import_media_folder(media, tmp_path / "results", transcribe=transcribe, prepare_audio=lambda source, _: [source])

    assert summary["files_success"] == 1
    assert summary["errors"] == [{"source_path": "broken.mp3", "error": "bad file"}]
    assert "good transcript" in Path(summary["timeline_path"]).read_text(encoding="utf-8")
