from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import backup_author_memory


ROOT = Path(__file__).resolve().parents[2]


class AuthorMemoryAclTests(unittest.TestCase):
    def test_windows_private_file_removes_inherited_acl_and_grants_current_user(self) -> None:
        path = Path("C:/private/backup.key")
        with (
            patch.object(backup_author_memory.os, "name", "nt"),
            patch.object(backup_author_memory.os, "chmod") as chmod,
            patch.object(backup_author_memory.subprocess, "run") as run,
        ):
            run.side_effect = [
                backup_author_memory.subprocess.CompletedProcess(
                    ["whoami"], 0, stdout="HOME_HP_NEW\\Segey\n", stderr=""
                ),
                backup_author_memory.subprocess.CompletedProcess(
                    ["icacls"], 0, stdout="", stderr=""
                ),
            ]
            backup_author_memory.restrict_private_file(path)

        chmod.assert_called_once_with(path, 0o600)
        self.assertEqual(run.call_count, 2)
        run.assert_any_call(
            ["whoami"],
            check=True,
            capture_output=True,
            text=True,
        )
        run.assert_any_call(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                "HOME_HP_NEW\\Segey:(F)",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    @unittest.skipUnless(shutil.which("bash"), "bash is unavailable")
    def test_server_uploader_rejects_sidecars_from_another_archive(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            incoming = Path(folder)
            (incoming / "author-memory-old.tar.gz.aes256").write_bytes(b"encrypted")
            (incoming / "author-memory-new.tar.gz.aes256.json").write_text("{}", encoding="utf-8")
            (incoming / "author-memory-new.tar.gz.aes256.sha256").write_text("hash", encoding="ascii")
            environment = dict(os.environ)
            environment["AUTHOR_MEMORY_BACKUP_DIR"] = incoming.as_posix()

            result = subprocess.run(
                [
                    shutil.which("bash"),
                    str(ROOT / "infra" / "scripts" / "upload-author-memory-backup.sh"),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Incomplete author-memory backup set", result.stderr)

    @unittest.skipUnless(shutil.which("bash"), "bash is unavailable")
    def test_server_uploader_rejects_invalid_archive_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            incoming = Path(folder)
            name = "author-memory-test.tar.gz.aes256"
            (incoming / name).write_bytes(b"encrypted")
            (incoming / f"{name}.sha256").write_text(
                f"{'0' * 64}  {name}\n", encoding="ascii"
            )
            (incoming / f"{name}.json").write_text(
                '{"archive":"author-memory-test.tar.gz.aes256","sha256":"'
                + "0" * 64
                + '"}',
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["AUTHOR_MEMORY_BACKUP_DIR"] = incoming.as_posix()

            result = subprocess.run(
                [
                    shutil.which("bash"),
                    str(ROOT / "infra" / "scripts" / "upload-author-memory-backup.sh"),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", result.stdout + result.stderr)


@unittest.skipUnless(backup_author_memory.AESGCM is not None, "cryptography is unavailable")
class AuthorMemoryBackupTests(unittest.TestCase):
    def test_encrypted_backup_round_trip_preserves_sources_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            voice = root / "voice"
            corrections = root / "corrections"
            voice.mkdir()
            corrections.mkdir()
            (voice / "correction-memory.jsonl").write_text(
                '{"correction_id":"one"}\n', encoding="utf-8"
            )
            (corrections / "owner-note.md").write_text("Точная правка", encoding="utf-8")
            output = root / "backup"
            key = root / "secrets" / "backup.key"

            result = backup_author_memory.create_backup(
                [("voice-v1", voice), ("corrections", corrections)],
                output,
                key,
                timestamp="20260828T120000Z",
            )

            encrypted = Path(result["archive"])
            self.assertTrue(encrypted.is_file())
            self.assertTrue(Path(result["checksum"]).is_file())
            self.assertTrue(Path(result["metadata"]).is_file())
            self.assertNotIn("Точная правка".encode("utf-8"), encrypted.read_bytes())
            self.assertFalse(any(output.glob("*.tar.gz")))

            restored = root / "restored"
            report = backup_author_memory.restore_backup(encrypted, key, restored)

            self.assertEqual(report["status"], "restored")
            self.assertEqual(
                (restored / "sources" / "voice-v1" / "correction-memory.jsonl").read_text(encoding="utf-8"),
                '{"correction_id":"one"}\n',
            )
            self.assertEqual(
                (restored / "sources" / "corrections" / "owner-note.md").read_text(encoding="utf-8"),
                "Точная правка",
            )
            self.assertTrue((restored / "manifest.json").is_file())

    def test_restore_rejects_wrong_key_without_writing_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            (source / "memory.jsonl").write_text("private", encoding="utf-8")
            result = backup_author_memory.create_backup(
                [("voice-v1", source)], root / "backup", root / "correct.key",
                timestamp="20260828T120000Z",
            )
            backup_author_memory.load_or_create_key(root / "wrong.key")

            destination = root / "restored"
            with self.assertRaisesRegex(ValueError, "authentication failed"):
                backup_author_memory.restore_backup(
                    Path(result["archive"]), root / "wrong.key", destination
                )
            self.assertFalse(destination.exists())

    def test_restore_rejects_missing_key_without_creating_one(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            (source / "memory.jsonl").write_text("private", encoding="utf-8")
            result = backup_author_memory.create_backup(
                [("voice-v1", source)], root / "backup", root / "correct.key",
                timestamp="20260828T120000Z",
            )
            missing = root / "missing.key"

            with self.assertRaisesRegex(FileNotFoundError, "backup key file is missing"):
                backup_author_memory.restore_backup(
                    Path(result["archive"]), missing, root / "restored"
                )

            self.assertFalse(missing.exists())
