from __future__ import annotations

import httpx

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    if not settings.telegram_test_bot_token:
        raise SystemExit("TELEGRAM_TEST_BOT_TOKEN is not configured")
    if not settings.telegram_public_base_url:
        raise SystemExit("TELEGRAM_PUBLIC_BASE_URL is not configured")
    if not settings.telegram_webhook_secret:
        raise SystemExit("TELEGRAM_WEBHOOK_SECRET is not configured")

    response = httpx.post(
        f"https://api.telegram.org/bot{settings.telegram_test_bot_token}/setWebhook",
        json={
            "url": f"{settings.telegram_public_base_url.rstrip('/')}/telegram/webhook",
            "secret_token": settings.telegram_webhook_secret,
            "drop_pending_updates": False,
        },
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise SystemExit(result.get("description", "Telegram rejected webhook"))
    print({"ok": True, "description": result.get("description", "")})


if __name__ == "__main__":
    main()
