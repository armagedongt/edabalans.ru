from __future__ import annotations

from .database import ArchiveDB
from .reports import rebuild_indexes
from .settings import Settings, ensure_data_dirs


def main() -> None:
    settings = Settings.load(require_auth=False)
    ensure_data_dirs(settings)
    db = ArchiveDB(settings.data_dir / "leadteh_archive.sqlite")
    try:
        rebuild_indexes(db, settings.data_dir)
    finally:
        db.close()
    print(f"Reports rebuilt in {settings.data_dir / 'reports'}")


if __name__ == "__main__":
    main()
