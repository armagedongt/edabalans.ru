"""Read-only MAX dependency checks, sampled away from public health requests."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from app.max import MAX_API_BASE, MaxClient


MAX_CHECK_INTERVAL_SECONDS = 30
MAX_CHECK_MAX_AGE_SECONDS = 75
MAX_REQUIRED_UPDATE_TYPES = {"bot_started", "bot_stopped", "dialog_removed", "message_created", "message_callback"}


@dataclass
class MaxHealth:
    checked_at: float | None = None
    reasons: list[str] = field(default_factory=lambda: ["max_check_pending"])

    def failure_reasons(self, now: float | None = None) -> list[str]:
        current = time.monotonic() if now is None else now
        if self.checked_at is None or current - self.checked_at > MAX_CHECK_MAX_AGE_SECONDS:
            return ["max_check_stale"]
        return list(self.reasons)


def check_max_dependencies(sender: MaxClient, expected_webhook_url: str, webhook_secret: str = "") -> list[str]:
    # Never include API response text or exception messages: they may contain tokens.
    dependency = "max_api"
    try:
        with sender._client(4) as api:
            me = api.get(f"{MAX_API_BASE}/me", headers={"Authorization": sender.token})
            me.raise_for_status()
            if me.json().get("is_bot") is not True:
                return ["max_unexpected_bot_response"]
            subscriptions = api.get(
                f"{MAX_API_BASE}/subscriptions", headers={"Authorization": sender.token},
            )
            subscriptions.raise_for_status()
            items = subscriptions.json().get("subscriptions")
            if not isinstance(items, list):
                return ["max_unexpected_subscriptions_response"]
            matching = [item for item in items if isinstance(item, dict) and item.get("url") == expected_webhook_url]
            if not matching:
                return ["max_webhook_missing"]
            if not any(
                item.get("update_types") is None
                or MAX_REQUIRED_UPDATE_TYPES.issubset(set(item.get("update_types", [])))
                for item in matching
            ):
                return ["max_webhook_events_missing"]
            if webhook_secret:
                # The authenticated unknown update is ignored by the real handler.
                # It verifies ingress without creating contacts or sending messages.
                dependency = "max_webhook"
                ingress = api.post(
                    expected_webhook_url,
                    headers={"X-Max-Bot-Api-Secret": webhook_secret},
                    json={"update_type": "runtime_health_probe"},
                )
                ingress.raise_for_status()
                if ingress.json() != {"ok": True, "ignored": True}:
                    return ["max_webhook_unexpected_response"]
            return []
    except httpx.HTTPStatusError as exc:
        return [f"{dependency}_http_{exc.response.status_code}"]
    except httpx.RequestError:
        return [f"{dependency}_unreachable"]
    except (ValueError, TypeError, AttributeError):
        return [f"{dependency}_invalid_response"]
