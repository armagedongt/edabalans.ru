from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Edabalans API"
    app_version: str = "0.2.0"
    database_url: str
    admin_username: str = ""
    admin_password: str = ""
    app_auth_secret: str = ""
    tilda_webhook_token: str = ""
    allowed_origins: str = "https://похудение-это-есть.рф"
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_ssl: bool = True
    smtp_starttls: bool = False
    telegram_test_bot_username: str = ""
    personal_access_page_url: str = "https://похудение-это-есть.рф/personal-access"
    pricing_catalog_enabled: bool = False

    @property
    def allowed_origins_list(self) -> list[str]:
        values = [item.strip() for item in self.allowed_origins.split(",") if item.strip()]
        expanded: list[str] = []
        for value in values:
            expanded.append(value)
            try:
                scheme, host = value.split("://", 1)
                expanded.append(f"{scheme}://{host.encode('idna').decode('ascii')}")
            except (UnicodeError, ValueError):
                pass
        return list(dict.fromkeys(expanded))

    model_config = SettingsConfigDict(case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
