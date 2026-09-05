from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.content_formatting import content_body_for_telegram


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(
        self,
        token: str,
        transport: httpx.BaseTransport | None = None,
        proxy_url: str = "",
        channel_id: str = "",
    ):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.transport = transport
        self.proxy_url = proxy_url
        self.channel_id = channel_id

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
        rendered_body = content_body_for_telegram(content)
        buttons = configuration.get("buttons") or []
        reply_markup = None
        if buttons:
            def button_action(button: dict[str, Any]) -> dict[str, Any]:
                if button.get("web_app"):
                    return {"web_app": button["web_app"]}
                if button.get("url"):
                    return {"url": button["url"]}
                return {"callback_data": button["callback_data"]}

            reply_markup = {
                "inline_keyboard": [[{
                    "text": button["text"],
                    **button_action(button),
                }] for button in buttons]
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
            if rendered_body and content.media_kind != "video_note":
                payload["caption"] = rendered_body
                payload["parse_mode"] = "HTML"
            local_path = Path(media_ref)
            result = self.upload(method, common | ({"caption": payload["caption"], "parse_mode": "HTML"} if "caption" in payload else {}), field, local_path) if local_path.is_file() else self.call(method, payload)
            telegram_media = result.get(field) or (result.get("photo") or [None])[-1]
            if isinstance(telegram_media, dict) and telegram_media.get("file_id"):
                content.telegram_file_id = telegram_media["file_id"]
        else:
            text = rendered_body or f"📎 Медиа будет добавлено позже: {content.title}"
            result = self.call("sendMessage", {**common, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False})
        return str(result["message_id"])

    def answer_callback(self, callback_query_id: str, text: str = "") -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})

    def set_chat_menu_web_app(self, chat_id: str, text: str, url: str) -> None:
        self.call(
            "setChatMenuButton",
            {
                "chat_id": int(chat_id),
                "menu_button": {
                    "type": "web_app",
                    "text": text,
                    "web_app": {"url": url},
                },
            },
        )

    def pin_message(self, chat_id: str, message_id: str) -> None:
        self.call("pinChatMessage", {"chat_id": chat_id, "message_id": message_id, "disable_notification": True})

    def delete_webhook(self) -> None:
        self.call("deleteWebhook", {"drop_pending_updates": False})

    def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query", "chat_member", "chat_join_request"]}
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", payload, timeout=timeout + 10)

    def get_chat(self, chat_id: str) -> dict[str, Any]:
        return self.call("getChat", {"chat_id": chat_id})

    def subscription_status(self, user_id: str) -> bool | None:
        if not self.channel_id:
            return None
        member = self.call("getChatMember", {"chat_id": self.channel_id, "user_id": user_id})
        status = member.get("status")
        if status in {"creator", "administrator", "member"}:
            return True
        if status == "restricted":
            return bool(member.get("is_member"))
        if status in {"left", "kicked"}:
            return False
        return None

    def create_chat_invite_link(self, chat_id: str, name: str, creates_join_request: bool = False) -> dict[str, Any]:
        return self.call("createChatInviteLink", {"chat_id": chat_id, "name": name[:32], "creates_join_request": creates_join_request})

    def revoke_chat_invite_link(self, chat_id: str, invite_link: str) -> dict[str, Any]:
        return self.call("revokeChatInviteLink", {"chat_id": chat_id, "invite_link": invite_link})
