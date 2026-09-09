from __future__ import annotations

from app.config import get_settings
from app.telegram import TelegramClient


def main() -> None:
    settings = get_settings()
    if not settings.telegram_test_bot_token:
        raise SystemExit("TELEGRAM_TEST_BOT_TOKEN is not configured")
    if not settings.telegram_public_base_url:
        raise SystemExit("TELEGRAM_PUBLIC_BASE_URL is not configured")
    if not settings.telegram_webhook_secret:
        raise SystemExit("TELEGRAM_WEBHOOK_SECRET is not configured")

    result = TelegramClient(
        settings.telegram_test_bot_token,
        proxy_url=settings.telegram_proxy_url,
        api_base_url=settings.telegram_api_base_url,
        gateway_token=settings.telegram_gateway_token,
    ).call(
        "setWebhook",
        {
            "url": f"{settings.telegram_public_base_url.rstrip('/')}/telegram/webhook",
            "secret_token": settings.telegram_webhook_secret,
            "drop_pending_updates": False,
        },
    )
    print({"ok": bool(result)})


if __name__ == "__main__":
    main()
