import os
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO


def snapshot(source: Path, output: BinaryIO) -> None:
    if not source.is_file():
        return
    with TemporaryDirectory() as temporary:
        copy = Path(temporary) / "board.sqlite3"
        with (
            closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as db,
            closing(sqlite3.connect(copy)) as target,
        ):
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='board' AND type='table'").fetchone():
                return
            db.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RuntimeError("Invalid Timeboard backup")
        with copy.open("rb") as file:
            shutil.copyfileobj(file, output)


if __name__ == "__main__":
    snapshot(Path(os.environ.get("TIMEBOARD_DB", "/var/lib/timeboard/board.sqlite3")), sys.stdout.buffer)
