import copy

import pytest

from tools import editorial_bot_adapter as bot


def original():
    return {"code": "tpl_day1", "title": "День 1", "content_version": 3,
            "purpose": "Выдать материал.", "writer_brief": "Сохранить {{personal_intensive_url}}.",
            "body_source": '\n<b>Текст</b>\n<a href="{{personal_intensive_url}}">Открыть</a>\n\n',
            "media_kind": None, "media_path": None, "editorial_status": "approved",
            "usages": [{"module": "welcome", "step": "day1"}],
            "allowed_variables": ["personal_intensive_url"],
            "buttons": [{"text": "Открыть", "callback": "old"}]}


class API:
    def __init__(self):
        self.item = original()
        self.calls = []
        self.invalid = False

    def request(self, method, path, payload=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if path == "/bot-api/content-audit":
            return {"items": [copy.deepcopy(self.item), {"code": None, "editorial_status": "missing_content"}]}
        if method == "GET":
            return copy.deepcopy(self.item)
        if self.invalid:
            raise ValueError("Validation rejected")
        if payload["expected_version"] != self.item["content_version"]:
            raise ValueError("409 version conflict")
        if method == "PUT":
            for name in ("body_source", "purpose", "writer_brief"):
                self.item[name] = payload[name].strip() if name != "body_source" else payload[name]
            self.item["content_version"] += 1
        return copy.deepcopy(self.item)


def test_discovery_uses_only_real_used_slots_and_keeps_context():
    api = API()
    items = bot.discover(api)
    assert list(items) == ["bot:tpl_day1"]
    assert items["bot:tpl_day1"]["usages"] == api.item["usages"]
    assert items["bot:tpl_day1"]["path"].endswith(".md")


def test_original_body_and_service_fields_roundtrip_without_strip_or_translation():
    item = original()
    parsed = bot.parse(bot.render(item))
    assert parsed == {key: item[key] for key in ("code", "purpose", "writer_brief", "body_source")}


def test_comparison_ignores_generated_header_and_context_but_detects_actual_body():
    item = original()
    before = bot.normalize(bot.render(item))
    item.update(content_version=99, title="Другое название", usages=[])
    assert bot.normalize(bot.render(item)) == before
    item["body_source"] += "**Markdown остаётся текстом**"
    assert bot.normalize(bot.render(item)) != before


def test_publish_selected_slot_uses_guard_and_never_changes_buttons_media_or_calls_send():
    api = API()
    original_fields = copy.deepcopy(api.item)
    item = bot.discover(api)["bot:tpl_day1"]
    source = bot.read(api, item)["text"].replace("<b>Текст</b>", "<b>Правка</b>")
    remote = bot.publish(api, item, source.replace("version: 3", "version: 900"), 3)
    assert remote["version"] == 4
    mutations = [call for call in api.calls if call[0] != "GET"]
    assert [(method, path) for method, path, _ in mutations] == [
        ("POST", "/bot-api/content/tpl_day1/validate"),
        ("PUT", "/bot-api/content/tpl_day1/publish")]
    assert mutations[1][2]["expected_version"] == 3
    assert set(mutations[1][2]) == {"body_source", "purpose", "writer_brief", "expected_version", "confirm"}
    for field in ("buttons", "media_kind", "media_path", "usages"):
        assert api.item[field] == original_fields[field]


def test_swapped_code_rejected_before_api_mutation():
    api = API()
    with pytest.raises(ValueError, match="Код"):
        bot.publish(api, {"code": "tpl_other"}, bot.render(api.item), 3)
    assert api.calls == []


@pytest.mark.parametrize("damage", [
    lambda text: text.replace("code: tpl_day1", "code: ../../day1"),
    lambda text: text.replace("version: 3", "version: zero"),
    lambda text: text.replace("<!-- ТЗ ПИСАТЕЛЮ", "<!-- ДРУГОЙ РАЗДЕЛ"),
    lambda text: text.replace("code: tpl_day1", "code: tpl_day1\ncode: tpl_other"),
])
def test_malformed_file_rejected_before_api_mutation(damage):
    api = API()
    with pytest.raises(ValueError):
        bot.publish(api, {"code": "tpl_day1"}, damage(bot._render_header(api.item)), 3)
    assert api.calls == []


@pytest.mark.parametrize("invalid,version,error", [(True, 3, "Validation"), (False, 2, "409")])
def test_validation_and_conflicts_prevent_publish(invalid, version, error):
    api = API()
    api.invalid = invalid
    with pytest.raises(ValueError, match=error):
        bot.publish(api, {"code": "tpl_day1"}, bot.render(api.item), version)
    assert len(api.calls) == 1
    assert api.calls[0][0] == "POST"
    assert api.item == original()


def test_empty_video_note_supported_without_artificial_caption():
    item = original()
    item.update(media_kind="video_note", body_source="")
    assert bot.parse(bot.render(item))["body_source"] == ""
    item["media_kind"] = None
    with pytest.raises(ValueError, match="Пустой"):
        bot.parse(bot.render(item))


def test_server_confirmation_must_match_exact_published_body():
    class DifferentConfirmationAPI(API):
        def request(self, method, path, payload=None):
            response = super().request(method, path, payload)
            if method == "GET":
                response["body_source"] = "Другой текст"
            return response

    api = DifferentConfirmationAPI()
    with pytest.raises(ValueError, match="Серверная редакция отличается"):
        bot.publish(api, {"code": "tpl_day1"}, bot.render(api.item), 3)


def test_server_trimming_service_fields_is_not_a_false_publication_conflict():
    api = API()
    working = copy.deepcopy(api.item)
    working["purpose"] = "\n  " + working["purpose"] + " \n"
    working["writer_brief"] = " " + working["writer_brief"] + "\n"
    remote = bot.publish(api, {"code": "tpl_day1"}, bot.render(working), 3)
    assert remote["version"] == 4
    assert api.item["purpose"] == original()["purpose"]
    assert api.item["body_source"] == original()["body_source"]


@pytest.mark.parametrize("code", ["tpl_intensive_masterclass_followup_image", "tpl_intensive_mid2_photo", "tpl_intensive_reminder_photo"])
@pytest.mark.parametrize("body", ["", "\n  \n"])
def test_photo_only_originals_read_and_normalize_without_fabricated_caption(code, body):
    api = API()
    api.item.update(code=code, media_kind="photo", media_path="existing-photo.jpg", body_source=body)
    item = bot.discover(api)["bot:" + code]
    remote = bot.read(api, item)
    assert bot.parse(remote["text"])["body_source"] == body
    assert bot.normalize(remote["text"])[-1] == body
    assert [method for method, _, _ in api.calls] == ["GET", "GET"]
    assert api.item["media_path"] == "existing-photo.jpg"


@pytest.mark.parametrize("media_kind", ["video", "voice"])
def test_server_supported_media_only_originals_are_lossless(media_kind):
    item = original(); item.update(media_kind=media_kind, body_source="")
    assert bot.parse(bot.render(item))["body_source"] == ""


@pytest.mark.parametrize("forged_kind", ["photo", "video_note"])
def test_media_header_cannot_bypass_actual_server_validation(forged_kind):
    class ServerValidatedAPI(API):
        def request(self, method, path, payload=None):
            if method == "POST" and path.endswith("/validate") and not payload["body_source"].strip():
                self.calls.append((method, path, copy.deepcopy(payload)))
                # Actual publication only permits empty video_note with real media.
                if self.item["media_kind"] != "video_note" or not self.item["media_path"]:
                    raise ValueError("Нельзя опубликовать пустой текст")
            return super().request(method, path, payload)

    api = ServerValidatedAPI()
    forged = copy.deepcopy(api.item); forged.update(media_kind=forged_kind, body_source="")
    with pytest.raises(ValueError, match="пустой текст"):
        bot.publish(api, {"code": api.item["code"]}, bot.render(forged), 3)
    assert len(api.calls) == 1 and api.calls[0][1].endswith("/validate")
    assert "media_kind" not in api.calls[0][2] and "media_path" not in api.calls[0][2]
    assert api.item == original()


def test_actual_photo_only_publication_rejection_preserves_original_and_never_calls_put():
    api = API()
    api.item.update(media_kind="photo", media_path="existing.jpg", body_source="")
    before = copy.deepcopy(api.item)
    api.invalid = True  # Existing server publication gate rejects a blank photo caption.
    with pytest.raises(ValueError, match="Validation rejected"):
        bot.publish(api, {"code": api.item["code"]}, bot.render(api.item), 3)
    assert api.item == before and len(api.calls) == 1 and api.calls[0][0] == "POST"


@pytest.mark.parametrize("damage", [lambda text: text.replace("media_kind: photo", "media_kind: photo\nmedia_kind: video_note"),
                                  lambda text: text.replace("media_kind: photo\n", "")])
def test_photo_only_malformed_header_is_rejected_before_any_request(damage):
    api = API(); api.item.update(media_kind="photo", body_source="")
    with pytest.raises(ValueError): bot.publish(api, {"code": api.item["code"]}, damage(bot._render_header(api.item)), 3)
    assert api.calls == []
