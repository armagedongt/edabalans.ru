from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./telegram-bot/runtime/service.sqlite"
    telegram_test_bot_username: str = ""
    telegram_test_bot_token: str = ""
    app_auth_secret: str = ""
    telegram_webhook_secret: str = ""
    telegram_public_base_url: str = ""
    telegram_proxy_url: str = ""
    telegram_api_base_url: str = ""
    telegram_gateway_token: str = ""
    telegram_channel_id: str = ""
    telegram_polling_enabled: bool = False
    telegram_polling_timeout_seconds: int = 25
    telegram_maintenance_mode: bool = False
    telegram_maintenance_allowed_user_ids: str = ""
    max_bot_username: str = ""
    max_bot_token: str = ""
    max_webhook_secret: str = ""
    max_channel_url: str = "https://max.ru/id230409966750_biz"
    max_contact_url: str = "https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw"
    yandex_oauth_token: str = ""
    yandex_metrika_counter_id: int = 97331502
    yandex_metrika_offline_enabled: bool = False
    yandex_metrika_offline_interval_seconds: float = 300.0
    admin_username: str = ""
    admin_password: str = ""
    scheduler_enabled: bool = False
    postpurchase_dispatch_enabled: bool = False
    postpurchase_test_only: bool = True
    auto_create_schema: bool = True
    scheduler_interval_seconds: float = 2.0
    media_root: str = "./telegram-bot/runtime/media"
    masterclass_offers_url: str = "https://похудение-это-есть.рф/lk"
    masterclass_course_url: str = "https://похудение-это-есть.рф/lk"
    masterclass_account_url: str = "https://edabalans.ru/lk"
    intensive_public_url: str = "https://edabalans.ru/intensive"
    public_link_allowed_origins: str = (
        "https://edabalans.ru,https://www.edabalans.ru,"
        "https://похудение-это-есть.рф,https://www.похудение-это-есть.рф"
    )
    @property
    def public_link_allowed_origins_list(self) -> list[str]:
        values = [item.strip() for item in self.public_link_allowed_origins.split(",") if item.strip()]
        expanded: list[str] = []
        for value in values:
            expanded.append(value)
            try:
                scheme, host = value.split("://", 1)
                expanded.append(f"{scheme}://{host.encode('idna').decode('ascii')}")
            except (UnicodeError, ValueError):
                pass
        return list(dict.fromkeys(expanded))

    model_config = SettingsConfigDict(
        env_file=("telegram-bot/.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
