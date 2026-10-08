from copy import deepcopy

import pytest

from tools import editorial_catalog_adapter as adapter


CATALOG = {"schemaVersion": 2, "products": [{"code": "masterclass", "shortName": "МК",
    "fullName": "Мастер-класс", "descriptor": "Описание", "marketing": "Текст", "status": "active"}],
    "tariffs": [{"code": "base", "name": "Базовый", "descriptor": "", "status": "active", "products": ["masterclass"]}]}
STRUCTURE = {"courseCode": "masterclass-21", "title": "Курс", "days": [
    {"number": 1, "title": "День", "checks": [{"id": "check-1", "text": "Задание"}],
     "steps": [{"id": "step-1", "title": "Урок", "label": "Урок", "required": True, "hidden": False},
               {"id": "step-2", "title": "Статья", "label": "Статья", "required": True, "hidden": False}]}]}


class API:
    def __init__(self, payload=CATALOG):
        self.payload = deepcopy(payload)
        self.version = 4
        self.calls = []
        self.confirmation_changes = False
        self.conflict_on_put = False

    def request(self, method, path, payload=None):
        self.calls.append((method, path, deepcopy(payload)))
        if path == "/admin/api/courses":
            return {"courses": [{"code": "masterclass-21", "name": "Мастер-класс"},
                                 {"code": "calories", "name": "Калорийный курс"},
                                 {"code": "unknown", "name": "Другой"}]}
        if path == "/admin/api/pricing":
            return {"live_consumption_enabled": True, "versions": [
                {"version_number": 6, "status": "draft", "entries": []},
                {"version_number": 5, "status": "active", "entries": [{"code": "base", "sale_amount": "100.00"}]}]}
        if method == "PUT":
            if self.conflict_on_put:
                raise ValueError("409 conflict")
            assert payload["expected_version"] == self.version
            new = payload.get("payload", payload.get("manifest"))
            if new != self.payload:
                self.version += 1
                self.payload = deepcopy(new)
            if self.confirmation_changes:
                self.payload["products"][0]["fullName"] = "Чужая редакция"
        return {"active": {"version": self.version, "manifest": deepcopy(self.payload)}}


def item(kind="catalog"):
    if kind == "catalog":
        return {"kind": kind, "id": "product:core", "title": "Каталог", "api_path": "/admin/api/product-catalog"}
    return {"kind": kind, "id": "names:masterclass-21", "title": "Названия", "api_path": "/admin/api/courses/masterclass-21/structure"}


def test_discovers_only_actual_supported_courses_and_pricing_explicitly_unsupported():
    items = adapter.discover(API())
    assert set(items) == {"product:core", "pricing:active", "names:masterclass-21", "names:calories"}
    assert items["pricing:active"]["unsupported"]


def test_working_file_roundtrips_full_original_without_duplicate_copy():
    source = adapter.render(item(), 4, CATALOG)
    assert source.count("```json") == 1
    assert adapter.parse(source) == ("product:core", CATALOG)


def test_compare_ignores_version_and_only_normalizes_actual_text_fields():
    source = adapter.render(item(), 4, CATALOG)
    payload = deepcopy(CATALOG)
    payload["products"][0]["fullName"] = "  Мастер-класс \n"
    assert adapter.normalize(adapter.render(item(), 99, payload)) == adapter.normalize(source)
    payload["products"][0]["code"] = " masterclass "
    assert adapter.normalize(adapter.render(item(), 99, payload)) != adapter.normalize(source)


def test_catalog_publishes_selected_actual_payload_with_stored_version():
    api = API()
    payload = deepcopy(CATALOG)
    payload["products"][0]["descriptor"] = "Новое описание"
    confirmed = adapter.publish(api, item(), adapter.render(item(), 900, payload), 4)
    assert confirmed["version"] == 5
    assert api.calls[1] == ("PUT", "/admin/api/product-catalog", {"expected_version": 4, "payload": payload})


def test_noop_publication_can_confirm_same_version():
    api = API()
    assert adapter.publish(api, item(), adapter.render(item(), 4, CATALOG), 4)["version"] == 4


@pytest.mark.parametrize("change", [
    lambda p: p["products"][0].update(code="other"),
    lambda p: p["tariffs"][0].update(products=[]),
    lambda p: p["products"].append(deepcopy(p["products"][0])),
])
def test_catalog_rejects_system_changes_before_put(change):
    api = API()
    payload = deepcopy(CATALOG)
    change(payload)
    with pytest.raises(ValueError):
        adapter.publish(api, item(), adapter.render(item(), 4, payload), 4)
    assert all(call[0] == "GET" for call in api.calls)


def test_names_renames_only_titles_and_keeps_progress_ids_and_checks():
    api = API(STRUCTURE)
    payload = deepcopy(STRUCTURE)
    payload["days"][0]["title"] = " Новое название "
    payload["days"][0]["steps"][0]["title"] = "Новый урок"
    confirmed = adapter.publish(api, item("names"), adapter.render(item("names"), 4, payload), 4)
    actual = adapter.parse(confirmed["text"])[1]
    assert actual["days"][0]["title"] == "Новое название"
    assert actual["days"][0]["checks"] == STRUCTURE["days"][0]["checks"]
    assert actual["days"][0]["steps"][0]["id"] == "step-1"


def test_calories_uses_actual_stages_original_and_same_version_guard():
    original = deepcopy(STRUCTURE)
    original["courseCode"] = "calories"
    original["stages"] = original.pop("days")
    api = API(original)
    calorie_item = {"kind": "names", "id": "names:calories", "title": "Названия этапов",
                    "api_path": "/admin/api/courses/calories/structure"}
    proposed = deepcopy(original)
    proposed["stages"][0]["title"] = "Новый этап"
    remote = adapter.publish(api, calorie_item, adapter.render(calorie_item, 4, proposed), 4)
    assert adapter.parse(remote["text"])[1] == proposed
    assert api.calls[1] == ("PUT", calorie_item["api_path"], {"expected_version": 4, "manifest": proposed})


@pytest.mark.parametrize("change", [
    lambda text: text.replace("```json", "```text"),
    lambda text: text + "\n```json\n{}\n```\n",
    lambda text: text.replace('"schemaVersion": 2', '"schemaVersion": bad'),
])
def test_malformed_original_is_rejected_before_api_calls(change):
    api = API()
    with pytest.raises(ValueError):
        adapter.publish(api, item(), change(adapter.render(item(), 4, CATALOG)), 4)
    assert not api.calls


@pytest.mark.parametrize("change", [
    lambda p: p["days"][0]["steps"].reverse(),
    lambda p: p["days"][0]["steps"][0].update(id="replacement"),
    lambda p: p["days"][0]["steps"][0].update(hidden=True),
    lambda p: p["days"][0]["checks"][0].update(text="Другое задание"),
    lambda p: p.update(title="Имя продукта"),
])
def test_names_cannot_reorder_or_change_runtime_structure(change):
    api = API(STRUCTURE)
    payload = deepcopy(STRUCTURE)
    change(payload)
    with pytest.raises(ValueError):
        adapter.publish(api, item("names"), adapter.render(item("names"), 4, payload), 4)
    assert all(call[0] == "GET" for call in api.calls)


def test_version_conflict_is_not_retried_and_result_must_match_original():
    api = API()
    with pytest.raises(ValueError, match="Конфликт"):
        adapter.publish(api, item(), adapter.render(item(), 4, CATALOG), 3)
    assert len(api.calls) == 1
    api = API()
    api.conflict_on_put = True
    with pytest.raises(ValueError, match="409"):
        adapter.publish(api, item(), adapter.render(item(), 4, CATALOG), 4)
    assert len(api.calls) == 2
    api = API()
    api.confirmation_changes = True
    with pytest.raises(ValueError, match="отличается"):
        adapter.publish(api, item(), adapter.render(item(), 4, CATALOG), 4)


def test_swapped_identity_rejected_before_api_call():
    api = API()
    with pytest.raises(ValueError, match="ID"):
        adapter.publish(api, item(), adapter.render(item("names"), 4, STRUCTURE), 4)
    assert not api.calls


def test_active_prices_original_is_readable_but_never_mutated_by_common_publisher():
    api = API()
    pricing = adapter.discover(api)["pricing:active"]
    remote = adapter.read(api, pricing)
    assert remote["version"] == 5
    assert remote["unsupported"]
    assert adapter.parse(remote["text"])[1]["entries"][0]["sale_amount"] == "100.00"
    with pytest.raises(ValueError, match="Цены"):
        adapter.publish(api, pricing, remote["text"], 5)
    assert all(call[0] == "GET" for call in api.calls)
