from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Edabalans API"
    app_version: str = "0.2.0"
    database_url: str
    admin_username: str = ""
    admin_password: str = ""

    model_config = SettingsConfigDict(case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
