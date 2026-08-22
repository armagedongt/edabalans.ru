from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"


@dataclass(frozen=True)
class Settings:
    bot_id: int
    base_url: str
    cookie: str | None
    token: str | None
    csrf_token: str | None
    delay_seconds: float
    jitter_min: float
    jitter_max: float
    timeout_seconds: float
    data_dir: Path = DATA_DIR

    @classmethod
    def load(cls, require_auth: bool = True) -> "Settings":
        load_dotenv(PROJECT_DIR / ".env")
        cookie = os.getenv("LEADTEH_COOKIE", "").strip() or None
        token = os.getenv("LEADTEH_TOKEN", "").strip() or None
        csrf_token = os.getenv("LEADTEH_CSRF_TOKEN", "").strip() or None
        if require_auth and not (cookie or token):
            raise ValueError(
                "Set LEADTEH_COOKIE or LEADTEH_TOKEN in leadteh-export/.env; "
                "never put credentials in source code."
            )
        jitter_min = float(os.getenv("LEADTEH_JITTER_MIN", "0.2"))
        jitter_max = float(os.getenv("LEADTEH_JITTER_MAX", "0.8"))
        if jitter_min < 0 or jitter_max < jitter_min:
            raise ValueError("Invalid jitter range")
        return cls(
            bot_id=int(os.getenv("LEADTEH_BOT_ID", "245278")),
            base_url=os.getenv("LEADTEH_BASE_URL", "https://app.leadteh.ru").rstrip("/"),
            cookie=cookie,
            token=token,
            csrf_token=csrf_token,
            delay_seconds=float(os.getenv("LEADTEH_DELAY_SECONDS", "1")),
            jitter_min=jitter_min,
            jitter_max=jitter_max,
            timeout_seconds=float(os.getenv("LEADTEH_TIMEOUT_SECONDS", "60")),
        )

    @property
    def tree_url(self) -> str:
        return f"{self.base_url}/api/bots/{self.bot_id}/schemas"

    @property
    def scenario_url(self) -> str:
        return f"{self.base_url}/api/bots/{self.bot_id}"


def ensure_data_dirs(settings: Settings) -> None:
    for relative in ("raw/scenarios", "parsed/scenarios", "parsed/content", "reports", "logs"):
        (settings.data_dir / relative).mkdir(parents=True, exist_ok=True)
