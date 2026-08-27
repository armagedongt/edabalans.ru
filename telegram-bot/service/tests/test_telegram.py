from types import SimpleNamespace

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
