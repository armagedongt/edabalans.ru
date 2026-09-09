from types import SimpleNamespace
import json

import httpx
import pytest

from app.telegram import TelegramClient, TelegramError


def test_local_media_is_uploaded_and_file_id_is_reused(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not-a-real-video")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7, "video": {"file_id": "cached-file"}}})

    content = SimpleNamespace(media_kind="video", media_path=str(media), telegram_file_id=None, body_source="Подпись", title="Видео")
    message_id = TelegramClient("secret", httpx.MockTransport(handler)).send_content("42", content, {})
    assert message_id == "7"
    assert content.telegram_file_id == "cached-file"
    assert b'filename="clip.mp4"' in seen[0].read()


def test_http_error_does_not_expose_bot_token():
    def handler(_):
        return httpx.Response(500, text="failure")

    with pytest.raises(TelegramError) as exc:
        TelegramClient("very-secret-token", httpx.MockTransport(handler)).call("sendMessage", {"chat_id": "42", "text": "x"})
    assert "very-secret-token" not in str(exc.value)


def test_relay_uses_gateway_headers_without_bot_token_in_url():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"id": 1}})

    result = TelegramClient(
        "123456:very-secret-token",
        httpx.MockTransport(handler),
        api_base_url="https://relay.example.test/telegram/",
        gateway_token="gateway-secret",
    ).call("getMe", {})

    assert result == {"id": 1}
    assert str(seen[0].url) == "https://relay.example.test/telegram/getMe"
    assert seen[0].headers["X-Edabalans-Relay-Token"] == "gateway-secret"
    assert seen[0].headers["X-Telegram-Bot-Token"] == "123456:very-secret-token"


def test_relay_bypasses_a_stale_legacy_proxy_setting(monkeypatch):
    observed = {}
    sentinel = object()

    def fake_httpx_client(**options):
        observed.update(options)
        return sentinel

    monkeypatch.setattr("app.telegram.httpx.Client", fake_httpx_client)
    client = TelegramClient(
        "123456:very-secret-token",
        proxy_url="http://unreliable-proxy.example.test:3128",
        api_base_url="https://relay.example.test/telegram",
        gateway_token="gateway-secret",
    )

    assert client._client(12) is sentinel
    assert "proxy" not in observed


def test_send_content_passes_validated_html_to_telegram_boundary():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 8}})

    content = SimpleNamespace(
        source_format="telegram_html",
        media_kind=None,
        media_path=None,
        telegram_file_id=None,
        body_source="<b>Готово</b>",
        title="HTML",
    )
    message_id = TelegramClient("secret", httpx.MockTransport(handler)).send_content("42", content, {})

    assert message_id == "8"
    payload = seen[0].read()
    assert '"text":"<b>Готово</b>"'.encode() in payload
    assert b'"parse_mode":"HTML"' in payload


def test_send_content_builds_web_app_button():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

    content = SimpleNamespace(
        source_format="telegram_html",
        media_kind=None,
        media_path=None,
        telegram_file_id=None,
        body_source="Откройте приложение",
        title="DQS",
    )
    TelegramClient("secret", httpx.MockTransport(handler)).send_content(
        "42",
        content,
        {
            "buttons": [{
                "text": "Открыть приложение",
                "web_app": {"url": "https://example.test/dqs"},
            }]
        },
    )

    payload = json.loads(seen[0].content)
    assert payload["reply_markup"] == {
        "inline_keyboard": [[{
            "text": "Открыть приложение",
            "web_app": {"url": "https://example.test/dqs"},
        }]]
    }


def test_edit_content_replaces_same_message_with_web_app_and_refresh_buttons():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

    content = SimpleNamespace(
        source_format="telegram_html",
        media_kind=None,
        media_path=None,
        telegram_file_id=None,
        body_source="<b>Мои приложения</b>",
        title="Приложения",
    )
    TelegramClient("secret", httpx.MockTransport(handler)).edit_content(
        "42",
        "9",
        content,
        {
            "buttons": [
                {"text": "DQS", "web_app": {"url": "https://example.test/dqs"}},
                {"text": "Обновить", "callback_data": "apps:refresh"},
            ]
        },
    )

    assert seen[0].url.path.endswith("/editMessageText")
    payload = json.loads(seen[0].content)
    assert payload["message_id"] == 9
    assert payload["reply_markup"]["inline_keyboard"][1][0]["callback_data"] == "apps:refresh"


def test_edit_content_accepts_unchanged_menu_as_success():
    def handler(_request):
        return httpx.Response(200, json={
            "ok": False,
            "description": "Bad Request: message is not modified",
        })

    content = SimpleNamespace(
        source_format="telegram_html",
        media_kind=None,
        media_path=None,
        telegram_file_id=None,
        body_source="<b>Мои приложения</b>",
        title="Приложения",
    )
    TelegramClient("secret", httpx.MockTransport(handler)).edit_content(
        "42", "9", content, {"buttons": [{"text": "Обновить", "callback_data": "apps:refresh"}]}
    )


def test_sets_personal_chat_menu_web_app():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": True})

    TelegramClient("secret", httpx.MockTransport(handler)).set_chat_menu_web_app(
        "42",
        "Интенсив",
        "https://app.edabalans.ru/intensive/start?i=Epersonal",
    )

    assert seen[0].url.path.endswith("/setChatMenuButton")
    assert json.loads(seen[0].content) == {
        "chat_id": 42,
        "menu_button": {
            "type": "web_app",
            "text": "Интенсив",
            "web_app": {
                "url": "https://app.edabalans.ru/intensive/start?i=Epersonal"
            },
        },
    }


def test_resets_personal_chat_menu_to_default():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": True})

    TelegramClient("secret", httpx.MockTransport(handler)).reset_chat_menu_button("42")

    assert seen[0].url.path.endswith("/setChatMenuButton")
    assert json.loads(seen[0].content) == {
        "chat_id": 42,
        "menu_button": {"type": "default"},
    }


def test_long_polling_sends_offset_and_returns_updates():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 101}]})

    updates = TelegramClient("secret", httpx.MockTransport(handler)).get_updates(offset=100, timeout=1)

    assert updates == [{"update_id": 101}]
    assert b'"offset":100' in seen[0].read()
    assert b'"timeout":1' in seen[0].content


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"status": "member"}, True),
        ({"status": "administrator"}, True),
        ({"status": "restricted", "is_member": True}, True),
        ({"status": "restricted", "is_member": False}, False),
        ({"status": "left"}, False),
    ],
)
def test_subscription_status_uses_real_channel_membership(result, expected):
    def handler(request):
        assert b'"chat_id":"-1001"' in request.read()
        return httpx.Response(200, json={"ok": True, "result": result})

    client = TelegramClient(
        "secret",
        httpx.MockTransport(handler),
        channel_id="-1001",
    )

    assert client.subscription_status("42") is expected


def test_subscription_status_is_unknown_without_channel():
    assert TelegramClient("secret").subscription_status("42") is None
