from __future__ import annotations

from app.config import get_settings
from app.max import MaxClient


UPDATE_TYPES = ["message_created", "message_edited", "message_removed"]


def main() -> None:
    settings = get_settings()
    missing = [
        name
        for name, value in {
            "BRIDGE_MAX_BOT_TOKEN": settings.bridge_max_bot_token,
            "BRIDGE_MAX_WEBHOOK_SECRET": settings.bridge_max_webhook_secret,
            "TELEGRAM_PUBLIC_BASE_URL": settings.telegram_public_base_url,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing configuration: {', '.join(missing)}")

    webhook_url = (
        f"{settings.telegram_public_base_url.rstrip('/')}/api/messaging/"
        "cross-messenger/max/webhook"
    )
    MaxClient(settings.bridge_max_bot_token).set_webhook_subscription(
        webhook_url,
        settings.bridge_max_webhook_secret,
        UPDATE_TYPES,
    )
    print({"ok": True, "webhook_url": webhook_url, "update_types": UPDATE_TYPES})


if __name__ == "__main__":
    main()
