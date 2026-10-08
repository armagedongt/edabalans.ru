from copy import deepcopy
import hashlib
import json

import pytest

from tools import editorial_pricing_adapter as adapter


ITEM = {"id": "pricing:active", "title": "Цены", "kind": "pricing", "api_path": adapter.PATH}
SOURCE = {"schema_version": 1, "name": "Тестовая редакция", "note": None, "entries": [
    {"code": "example-base", "section": "fictional", "name": "Вымышленный продукт", "product_code": "example",
     "stage_code": None, "resource_codes": ["EXAMPLE_ACCESS"], "item_count": 1, "regular_amount": "200.00",
     "compare_at_amount": None, "sale_amount": "100.00", "currency": "RUB", "enabled": True,
     "sort_order": 7, "metadata": {"business": "keep"}},
    {"code": "example-plus", "section": "fictional", "name": "Вымышленный продукт 2", "product_code": "example",
     "stage_code": "plus", "resource_codes": ["EXAMPLE_PLUS"], "item_count": 2, "regular_amount": None,
     "compare_at_amount": "250.00", "sale_amount": "150.00", "currency": "RUB", "enabled": True,
     "sort_order": 9, "metadata": {"business": {"nested": True}}},
]}


def revision(version):
    source = deepcopy(version["source"])
    source["entries"].sort(key=lambda row: row["code"])
    digest = hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"id": version["id"], "version_number": version["version_number"], "sha256": digest}


def version(number, payload=SOURCE, status="active", base=None):
    result = {"id": f"00000000-0000-0000-0000-{number:012d}", "version_number": number, "status": status,
              "source": deepcopy(payload), "base_active": deepcopy(base), "authoring_ready": status == "draft"}
    result["revision"] = revision(result)
    return result


class API:
    """Server boundary with independent revision checks and accepted-response loss."""
    def __init__(self):
        self.active = version(4)
        self.draft = None
        self.calls = []
        self.lose = None
        self.corrupt_update = False
        self.concurrent_publish = False

    def request(self, method, path, payload=None):
        self.calls.append((method, path, deepcopy(payload)))
        if method == "GET":
            return {"versions": deepcopy([v for v in (self.active, self.draft) if v]),
                    "active_revision": self.active["revision"] if self.active else None,
                    "draft_revision": self.draft["revision"] if self.draft else None, "live_consumption_enabled": False}
        assert payload["expected_active"] == self.active["revision"], "stale active guard"
        if path.endswith("/drafts"):
            assert self.draft is None and payload["expected_draft"] is None
            cloned = deepcopy(self.active["source"])
            min(cloned["entries"], key=lambda row: row["code"])["metadata"][adapter.STAMP] = {
                "schema_version": 1, "owner": "platform.commerce", "base_active": deepcopy(self.active["revision"])}
            self.draft = version(8, cloned, "draft", self.active["revision"])
            result = self.draft
            operation = "create"
        else:
            assert payload["expected_draft"] == self.draft["revision"], "stale draft guard"
            assert self.draft["id"] in path
            if method == "PUT":
                assert payload.keys() == {"expected_active", "expected_draft", "name", "note", "entries"}
                for new, old in zip(payload["entries"], self.draft["source"]["entries"], strict=True):
                    assert new.keys() == {"code", *adapter.MONEY, "enabled"}
                    assert new["code"] == old["code"] and new["enabled"] == old["enabled"]
                    old.update(new)
                self.draft["source"].update(name=payload["name"].strip(), note=(payload["note"] or "").strip() or None)
                if self.corrupt_update:
                    self.draft["source"]["entries"][0]["sale_amount"] = "111.00"
                self.draft["revision"] = revision(self.draft)
                result, operation = self.draft, "update"
            else:
                assert payload["confirm"] is True
                if self.concurrent_publish:
                    self.active = version(10)
                    raise ValueError("409 concurrent active")
                self.active = self.draft
                self.active["status"] = "active"
                self.active["authoring_ready"] = False
                self.draft = None
                result, operation = self.active, "publish"
        if operation == self.lose:
            raise TimeoutError("accepted response lost")
        return {"ok": True, "version": deepcopy(result)}


def desired(remote):
    source = deepcopy(remote["source"])
    source["name"] = " Новая вымышленная редакция "
    source["note"] = " Тест "
    source["entries"][0]["sale_amount"] = "90.25"
    return adapter.render(ITEM, 4, source)


def writes(api):
    return [call for call in api.calls if call[0] != "GET"]


def test_guarded_publish_preserves_business_and_uses_revision_objects():
    api = API()
    remote = adapter.read(api, ITEM)
    result = adapter.publish(api, ITEM, desired(remote), remote)
    assert result["version"]["version_number"] == 8  # Never assume active + 1.
    assert adapter.normalize(result["text"]) == adapter.normalize(desired(remote))
    assert result["format"] == "pricing-json-v1"
    assert result["source"]["entries"][1] == SOURCE["entries"][1]
    assert result["source"]["entries"][0]["metadata"]["business"] == "keep"
    assert [c[0] for c in writes(api)] == ["POST", "PUT", "POST"]
    assert writes(api)[-1][2]["expected_active"] == remote["version"]


def test_noop_does_not_create_or_activate_draft():
    api = API()
    remote = adapter.read(api, ITEM)
    adapter.publish(api, ITEM, remote["text"], remote)
    assert not writes(api)


@pytest.mark.parametrize("field,value", [("enabled", False), ("code", "renamed-code"),
    ("resource_codes", ["OTHER"]), ("sort_order", 1), ("metadata", {}), ("currency", "USD")])
def test_system_field_changes_rejected_before_writes(field, value):
    api = API()
    remote = adapter.read(api, ITEM)
    changed = deepcopy(SOURCE)
    changed["entries"][0][field] = value
    with pytest.raises(ValueError):
        adapter.publish(api, ITEM, adapter.render(ITEM, 4, changed), remote)
    assert not writes(api)


def test_system_boolean_cannot_replace_numeric_item_count():
    api = API(); remote = adapter.read(api, ITEM)
    changed = deepcopy(SOURCE); changed["entries"][0]["item_count"] = True
    with pytest.raises(ValueError): adapter.publish(api, ITEM, adapter.render(ITEM, 4, changed), remote)
    assert not writes(api)


@pytest.mark.parametrize("mutation", ["order", "remove", "add"])
def test_structure_changes_are_not_price_edits(mutation):
    api = API()
    remote = adapter.read(api, ITEM)
    changed = deepcopy(SOURCE)
    if mutation == "order": changed["entries"].reverse()
    elif mutation == "remove": changed["entries"].pop()
    else:
        row = deepcopy(changed["entries"][0]); row["code"] = "example-extra"; changed["entries"].append(row)
    with pytest.raises(ValueError): adapter.publish(api, ITEM, adapter.render(ITEM, 4, changed), remote)
    assert not writes(api)


@pytest.mark.parametrize("value", [True, "NaN", "Infinity", "1.001", "-1", "10000001", None, {}, []])
def test_invalid_money_rejected(value):
    changed = deepcopy(SOURCE)
    changed["entries"][0]["sale_amount"] = value
    with pytest.raises(ValueError): adapter.normalize(adapter.render(ITEM, 4, changed))


@pytest.mark.parametrize("entries", [None, {}, [], [None], ["wrong"]])
def test_malformed_array_is_value_error(entries):
    changed = deepcopy(SOURCE); changed["entries"] = entries
    with pytest.raises(ValueError): adapter.normalize(adapter.render(ITEM, 4, changed))


def test_only_valid_first_row_stamp_is_inert():
    marked = deepcopy(SOURCE)
    stamp = {"schema_version": 1, "owner": "platform.commerce", "base_active": version(4)["revision"]}
    marked["entries"][0]["metadata"][adapter.STAMP] = stamp
    assert adapter.canonical(marked) == adapter.canonical(SOURCE)
    marked["entries"][0]["metadata"][adapter.STAMP]["owner"] = "someone-else"
    assert adapter.canonical(marked) != adapter.canonical(SOURCE)
    marked = deepcopy(SOURCE); marked["entries"][1]["metadata"][adapter.STAMP] = stamp
    assert adapter.canonical(marked) != adapter.canonical(SOURCE)


def test_no_active_original_is_unsupported_never_uses_draft():
    api = API(); api.active = None; api.draft = version(1, status="draft")
    with pytest.raises(ValueError, match="Нет опубликованной версии"):
        adapter.read(api, ITEM)
    with pytest.raises(ValueError): adapter.publish(api, ITEM, adapter.render(ITEM, 1, SOURCE), {"unsupported": True})
    assert not writes(api)


@pytest.mark.parametrize("kind", ["other", "stale", "unhealthy"])
def test_existing_draft_cannot_be_overwritten(kind):
    api = API(); remote = adapter.read(api, ITEM)
    api.draft = version(8, adapter.parse(desired(remote)), "draft", remote["version"])
    if kind == "other": api.draft["source"]["note"] = "Another author"
    elif kind == "stale": api.draft["base_active"] = version(3)["revision"]
    else: api.draft["authoring_ready"] = False
    api.draft["revision"] = revision(api.draft)
    with pytest.raises(ValueError): adapter.publish(api, ITEM, desired(remote), remote)
    assert not writes(api)


def test_exact_existing_draft_reuses_only_publish():
    api = API(); remote = adapter.read(api, ITEM)
    api.draft = version(8, adapter.parse(desired(remote)), "draft", remote["version"])
    adapter.publish(api, ITEM, desired(remote), remote)
    assert [c[1] for c in writes(api)] == [adapter.PATH + "/versions/" + version(8)["id"] + "/publish"]


@pytest.mark.parametrize("operation", ["update", "publish"])
def test_lost_accepted_response_recovers_only_exact_source(operation):
    api = API(); api.lose = operation; remote = adapter.read(api, ITEM)
    result = adapter.publish(api, ITEM, desired(remote), remote)
    assert adapter.normalize(result["text"]) == adapter.normalize(desired(remote))
    assert len(writes(api)) == 3
    again = adapter.publish(api, ITEM, desired(remote), remote)
    assert again["version"] == result["version"] and len(writes(api)) == 3


def test_lost_create_response_aborts_and_does_not_adopt_clone_on_retry():
    api = API(); api.lose = "create"; remote = adapter.read(api, ITEM)
    with pytest.raises(TimeoutError): adapter.publish(api, ITEM, desired(remote), remote)
    with pytest.raises(ValueError): adapter.publish(api, ITEM, desired(remote), remote)
    assert len(writes(api)) == 1


def test_lost_update_with_other_source_never_activates():
    api = API(); api.lose = "update"; api.corrupt_update = True; remote = adapter.read(api, ITEM)
    with pytest.raises(TimeoutError): adapter.publish(api, ITEM, desired(remote), remote)
    assert len(writes(api)) == 2 and api.active["version_number"] == 4


def test_concurrent_active_change_is_not_adopted():
    api = API(); remote = adapter.read(api, ITEM); api.active = version(10)
    with pytest.raises(ValueError): adapter.publish(api, ITEM, desired(remote), remote)
    assert not writes(api)


def test_concurrent_change_during_publish_aborts():
    api = API(); api.concurrent_publish = True; remote = adapter.read(api, ITEM)
    with pytest.raises(ValueError, match="concurrent"): adapter.publish(api, ITEM, desired(remote), remote)
    assert api.active["version_number"] == 10


def test_header_swap_rejected_and_version_header_ignored():
    text = adapter.render(ITEM, 4, SOURCE)
    assert adapter.normalize(text) == adapter.normalize(text.replace("version: 4", "version: 999"))
    with pytest.raises(ValueError): adapter.normalize(text.replace("pricing:active", "product:core"))


@pytest.mark.parametrize("target", ["active", "draft"])
def test_read_rejects_source_tampered_without_revision_hash(target):
    api = API()
    api.draft = version(8, status="draft", base=api.active["revision"])
    getattr(api, target)["source"]["entries"][0]["sale_amount"] = "99.00"
    with pytest.raises(ValueError, match="hash"):
        adapter.read(api, ITEM)


@pytest.mark.parametrize("bad_revision", [None, "wrong", {"id": "not-uuid", "version_number": 8, "sha256": "a" * 64},
    {"id": version(8)["id"], "version_number": True, "sha256": "a" * 64}])
def test_read_rejects_malformed_draft_revision_before_writes(bad_revision):
    api = API(); api.draft = version(8, status="draft", base=api.active["revision"])
    api.draft["revision"] = bad_revision
    with pytest.raises(ValueError, match="ревизи"):
        adapter.read(api, ITEM)
    assert not writes(api)
