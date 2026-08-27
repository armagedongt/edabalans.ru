from __future__ import annotations

from pathlib import Path
import sys


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "telegram-bot" / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from app.content_authoring_cli import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
