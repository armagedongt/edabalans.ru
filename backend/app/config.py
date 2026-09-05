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
    smtp_from_name: str = "Сергей Воронцов · Похудение — это есть!"
    smtp_reply_to: str = "armagedongt@gmail.com"
    smtp_use_ssl: bool = True
    smtp_starttls: bool = False
    telegram_test_bot_username: str = "Fitness_Talks_bot"
    max_bot_username: str = "id230409966750_bot"
    account_telegram_bot_username: str = "Fitness_Talks_bot"
    account_max_bot_username: str = "id230409966750_bot"
    account_public_url: str = "https://go.похудение-это-есть.рф/lk"
    account_onboarding_enabled: bool = False
    account_session_days: int = 30
    account_email_worker_enabled: bool = True
    account_email_poll_seconds: float = 15.0
    masterclass_course_url: str = "https://похудение-это-есть.рф/lk"
    personal_access_page_url: str = "https://похудение-это-есть.рф/personal-access"
    pricing_catalog_enabled: bool = False
    robokassa_checkout_enabled: bool = False
    robokassa_test_mode: bool = True
    robokassa_merchant_login: str = ""
    robokassa_password_1: str = ""
    robokassa_test_password_1: str = ""
    robokassa_hash_algorithm: str = "sha256"
    robokassa_payment_url: str = "https://auth.robokassa.ru/Merchant/Index.aspx"
    robokassa_result_url_2: str = "https://app.edabalans.ru/integrations/robokassa/result2"
    robokassa_success_url_2: str = "https://app.edabalans.ru/payments/robokassa/success"
    robokassa_fail_url_2: str = "https://app.edabalans.ru/payments/robokassa/fail"
    robokassa_jws_certificate_base64: str = ""
    robokassa_receipt_sno: str = ""
    robokassa_receipt_tax: str = ""
    robokassa_receipt_payment_method: str = "full_payment"
    robokassa_receipt_payment_object: str = "service"
    knowledge_mcp_token: str = ""
    yandex_metrika_counter_id: str = "97331502"
    yandex_direct_token: str = ""
    yandex_direct_client_login: str = ""
    marketing_day_one_events_enabled: bool = False
    marketing_site_home_events_enabled: bool = False
    marketing_later_day_events_enabled: bool = False
    intensive_day_1_telegram_post_url: str = ""
    intensive_day_1_max_post_url: str = ""
    intensive_day_2_telegram_post_url: str = ""
    intensive_day_2_max_post_url: str = ""
    intensive_day_3_telegram_post_url: str = ""
    intensive_day_3_max_post_url: str = ""

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
