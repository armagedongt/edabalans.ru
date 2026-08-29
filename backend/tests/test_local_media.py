import hashlib
import json
from pathlib import Path

from app.importers.local_media import _safe_name, import_media_folder


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
