from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None, proxy_url: str = ""):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.transport = transport
        self.proxy_url = proxy_url

    def _client(self, timeout: float) -> httpx.Client:
        options: dict[str, Any] = {"timeout": timeout, "transport": self.transport}
        if self.proxy_url and self.transport is None:
            options["proxy"] = self.proxy_url
        return httpx.Client(**options)

    def call(self, method: str, payload: dict[str, Any], timeout: float = 30) -> Any:
        with self._client(timeout) as client:
            response = client.post(f"{self.base_url}/{method}", json=payload)
        if not response.is_success:
            raise TelegramError(f"Telegram API HTTP {response.status_code}")
        data = response.json()
        if not data.get("ok"):
            raise TelegramError(data.get("description", "Telegram API error"))
        return data["result"]

    def upload(self, method: str, payload: dict[str, Any], field: str, path: Path) -> dict[str, Any]:
        form = dict(payload)
        reply_markup = form.get("reply_markup")
        if reply_markup:
            import json
            form["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        with path.open("rb") as stream, self._client(120) as client:
            response = client.post(f"{self.base_url}/{method}", data=form, files={field: (path.name, stream)})
        if not response.is_success:
            raise TelegramError(f"Telegram API upload HTTP {response.status_code}")
        data = response.json()
        if not data.get("ok"):
            raise TelegramError(data.get("description", "Telegram API upload error"))
        return data["result"]

    def send_content(self, chat_id: str, content: Any, configuration: dict[str, Any]) -> str:
        buttons = configuration.get("buttons") or []
        reply_markup = None
        if buttons:
            reply_markup = {
                "inline_keyboard": [[{"text": b["text"], "callback_data": b["callback_data"]}] for b in buttons]
            }
        common: dict[str, Any] = {"chat_id": chat_id}
        if reply_markup:
            common["reply_markup"] = reply_markup

        media_ref = content.telegram_file_id or content.media_path
        if content.media_kind in {"video_note", "video", "voice", "photo"} and media_ref:
            method, field = {
                "video_note": ("sendVideoNote", "video_note"),
                "video": ("sendVideo", "video"),
                "voice": ("sendVoice", "voice"),
                "photo": ("sendPhoto", "photo"),
            }[content.media_kind]
            payload = {**common, field: media_ref}
            if content.body_source and content.media_kind != "video_note":
                payload["caption"] = content.body_source
                payload["parse_mode"] = "HTML"
            local_path = Path(media_ref)
            result = self.upload(method, common | ({"caption": payload["caption"], "parse_mode": "HTML"} if "caption" in payload else {}), field, local_path) if local_path.is_file() else self.call(method, payload)
            telegram_media = result.get(field) or (result.get("photo") or [None])[-1]
            if isinstance(telegram_media, dict) and telegram_media.get("file_id"):
                content.telegram_file_id = telegram_media["file_id"]
        else:
            text = content.body_source or f"📎 Медиа будет добавлено позже: {content.title}"
            result = self.call("sendMessage", {**common, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False})
        return str(result["message_id"])

    def answer_callback(self, callback_query_id: str, text: str = "") -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})

    def delete_webhook(self) -> None:
        self.call("deleteWebhook", {"drop_pending_updates": False})

    def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", payload, timeout=timeout + 10)
