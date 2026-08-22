from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./telegram-bot/runtime/service.sqlite"
    telegram_test_bot_username: str = ""
    telegram_test_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_public_base_url: str = ""
    telegram_proxy_url: str = ""
    telegram_channel_id: str = ""
    telegram_polling_enabled: bool = False
    telegram_polling_timeout_seconds: int = 25
    admin_username: str = ""
    admin_password: str = ""
    scheduler_enabled: bool = False
    postpurchase_dispatch_enabled: bool = False
    auto_create_schema: bool = True
    scheduler_interval_seconds: float = 2.0
    media_root: str = "./telegram-bot/runtime/media"
    masterclass_offers_url: str = ""

    model_config = SettingsConfigDict(
        env_file=("telegram-bot/.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
