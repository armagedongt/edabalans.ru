import json
from pathlib import Path

import pytest

from tools.editorial_vault import Vault, VaultError, atomic_json, comparable, digest, update_if_unchanged


class FakeAPI:
    def __init__(self, kind="public"):
        self.kind = kind
        self.text = "Оригинальный текст\n"
        self.version = 1
        self.published = True
        self.calls = []
        self.fail_publish = False
        self.edit_while_publishing = None

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET":
            if self.kind == "course":
                return {"version": self.version, "source_content": self.text, "source_format": "markdown", "html": "<p>Текст</p>", "title": "Материал"}
            data = {"version": self.version, "markdown": self.text, "title": "Материал",
                    "editorial_status": "published" if self.published else "moderation"}
            return {"active" if self.kind == "public" else "article": data}
        if method == "POST":
            if self.fail_publish:
                raise TimeoutError("Сеть")
            self.published = True
        else:
            assert payload["expected_version"] == self.version
            self.version += 1
            self.text = payload.get("markdown", payload.get("content"))
            if self.kind == "public":
                self.text = "<!-- public-site-version: " + str(self.version) + " -->\n\n" + self.text.strip()
            self.published = self.kind == "public"
            if self.edit_while_publishing:
                self.edit_while_publishing()
        return {"active" if self.kind == "public" else "article": {"version": self.version}}


def vault_fixture(tmp_path, kind="public"):
    api = FakeAPI(kind)
    vault = Vault(tmp_path, api)
    vault.state_path.parent.mkdir(parents=True)
    item = {"kind": kind, "group": "Раздел", "title": "Материал", "api_path": "/admin/api/material",
            "path": "Материал.md", "base_version": 1, "base_hash": digest(comparable(api.text, kind))}
    atomic_json(vault.state_path, {"schema": 1, "items": {"one": item}})
    (tmp_path / "Материал.md").write_text(api.text, encoding="utf-8")
    vault.discover = lambda: {"one": item}
    return vault, api, tmp_path / "Материал.md"


@pytest.mark.parametrize("supported", [False, True])
def test_source_current_only_server_profile_allows_first_full_md_put(tmp_path, supported):
    vault, api, file = vault_fixture(tmp_path, "course")
    state = vault.load()
    state["items"]["one"].update(base_version=0, unsupported=True)
    atomic_json(vault.state_path, state)
    api.version = 0
    original = api.request
    def request(method, path, payload=None):
        result = original(method, path, payload)
        if method == "GET":
            result["source_provenance"] = "git_markdown" if api.version == 0 else "editorial_source"
            if supported:
                result.update(publication_profile={"type": "api", "render_profile": "masterclass-source-current"},
                              source_hash=digest(api.text))
        return result
    api.request = request
    vault.refresh()
    file.write_text("Полный Markdown с правками", encoding="utf-8")
    row = vault.publish(["one"], owner_edited=True)[0]
    if supported:
        assert row["status"] == "published"
        payload = next(c[2] for c in api.calls if c[0] == "PUT")
        assert payload["expected_version"] == 0 and payload["expected_source_hash"] == digest("Оригинальный текст\n")
        assert api.text == "Полный Markdown с правками"
    else:
        assert row["status"] == "error" and all(c[0] == "GET" for c in api.calls)


def test_invalid_structured_file_does_not_hide_other_materials(tmp_path):
    vault, api, file = vault_fixture(tmp_path)
    state = vault.load()
    state["items"]["broken"] = {**state["items"]["one"], "kind": "graph", "path": "Broken.md"}
    atomic_json(vault.state_path, state)
    (tmp_path / "Broken.md").write_text("{broken", encoding="utf-8")
    rows = {row["id"]: row for row in vault.status()}
    assert rows["one"]["status"] == "clean"
    assert rows["broken"]["status"] == "invalid"
    assert rows["broken"]["message"]
    assert api.calls == []


@pytest.mark.parametrize("bad", [None, ["bad"], {}])
def test_invalid_catalog_array_keeps_other_materials_available(tmp_path, bad):
    from tools.editorial_catalog_adapter import render
    vault, api, file = vault_fixture(tmp_path)
    item = {"id": "product:core", "kind": "catalog", "title": "Каталог", "path": "Catalog.md", "base_hash": "unused"}
    state = vault.load()
    state["items"]["product:core"] = item
    atomic_json(vault.state_path, state)
    (tmp_path / "Catalog.md").write_text(render(item, 1, {"products": bad, "tariffs": []}), encoding="utf-8")
    rows = {row["id"]: row for row in vault.status()}
    assert rows["one"]["status"] == "clean"
    assert rows["product:core"]["status"] == "invalid"
    assert api.calls == []


def test_graph_activation_and_lost_response_do_not_use_numeric_version_arithmetic(tmp_path, monkeypatch):
    from tools import editorial_graph_adapter as adapter
    source = json.dumps({"schema_version": 1, "sequence": {"code": "welcome_intensive", "name": "Цепочка"},
                         "steps": [{"key": "start", "position": 1, "configuration": {}}], "edges": []})
    vault = Vault(tmp_path, FakeAPI())
    vault.state_path.parent.mkdir(parents=True)
    remote = {"text": source, "version": {"version": 1, "sha256": "a" * 64}, "title": "Цепочка", "editorial_owned": False}
    item = {"kind": "graph", "code": "welcome_intensive", "group": "Логика бота", "title": "Цепочка",
            "path": "Graph.md", "base_version": remote["version"], "base_hash": digest(comparable(source, "graph"))}
    atomic_json(vault.state_path, {"schema": 1, "items": {"graph:welcome_intensive": item}})
    (tmp_path / "Graph.md").write_text(source, encoding="utf-8")
    monkeypatch.setattr(adapter, "read", lambda api, item: dict(remote))
    writes = []
    def activate(api, item, text, expected):
        writes.append(text)
        remote.update(version={"version": 7, "sha256": "b" * 64}, editorial_owned=True)
        raise TimeoutError("Ответ потерян после принятия")
    monkeypatch.setattr(adapter, "publish", activate)
    assert vault.publish(["graph:welcome_intensive"])[0]["status"] == "error"
    assert vault.publish(["graph:welcome_intensive"])[0]["status"] == "clean"
    assert len(writes) == 1
    assert vault.load()["items"]["graph:welcome_intensive"]["base_version"] == remote["version"]


def legacy_pricing_fixture(tmp_path):
    from tools.tests.test_editorial_pricing_adapter import API, ITEM, SOURCE
    from tools.editorial_catalog_adapter import render, normalize
    api = API()
    vault = Vault(tmp_path, api)
    item = {**ITEM, "group": "Каталог", "path": "Цены.md", "format": "markdown", "unsupported": True,
            "base_version": 4}
    text = render(item, 4, {"version_number": 4, "status": "active", "name": SOURCE["name"],
                            "note": SOURCE["note"], "entries": SOURCE["entries"]})
    item["base_hash"] = digest(normalize(text))
    vault.state_path.parent.mkdir(parents=True)
    atomic_json(vault.state_path, {"schema": 1, "items": {"pricing:active": item}})
    file = tmp_path / item["path"]
    file.write_text(text, encoding="utf-8")
    vault.discover = lambda: {"pricing:active": item}
    return vault, api, file


def test_clean_readonly_prices_migrate_in_same_file_to_guarded_original(tmp_path):
    vault, api, file = legacy_pricing_fixture(tmp_path)
    assert vault.refresh()[0]["status"] == "clean"
    item = vault.load()["items"]["pricing:active"]
    assert item["path"] == "Цены.md" and item["format"] == "pricing-json-v1"
    assert item["base_version"] == api.active["revision"]
    assert item["unsupported"] is False
    assert vault.status()[0]["status"] == "clean"
    assert all(call[0] == "GET" for call in api.calls)


def test_refresh_preserves_inconsistent_accepted_prices_in_actual_original_file(tmp_path):
    from copy import deepcopy
    from tools.tests.test_editorial_pricing_adapter import SOURCE, version
    from tools.editorial_pricing_adapter import parse
    vault, api, file = legacy_pricing_fixture(tmp_path)
    accepted = deepcopy(SOURCE); accepted["entries"][0]["regular_amount"] = "50.00"
    api.active = version(4, accepted)
    assert vault.refresh()[0]["status"] == "clean"
    assert parse(file.read_text(encoding="utf-8"))["entries"] == accepted["entries"]
    assert vault.load()["items"]["pricing:active"]["base_version"] == api.active["revision"]
    assert vault.status()[0]["status"] == "clean"
    assert vault.publish(["pricing:active"])[0]["status"] == "clean"
    assert all(call[0] == "GET" for call in api.calls)


def test_dirty_legacy_prices_are_preserved_without_inventing_new_base(tmp_path):
    vault, api, file = legacy_pricing_fixture(tmp_path)
    original_state = vault.load()
    draft = file.read_text(encoding="utf-8").replace('"100.00"', '"95.00"')
    file.write_text(draft, encoding="utf-8")
    assert vault.refresh()[0]["status"] == "error"
    assert file.read_text(encoding="utf-8") == draft
    assert vault.load() == original_state
    assert all(call[0] == "GET" for call in api.calls)


def test_price_migration_preserves_edit_made_during_refresh(tmp_path, monkeypatch):
    vault, api, file = legacy_pricing_fixture(tmp_path)
    original_state = vault.load()
    def concurrent_edit(path, expected, replacement):
        path.write_text("Правка во время обновления", encoding="utf-8")
        return False
    monkeypatch.setattr("tools.editorial_vault.update_if_unchanged", concurrent_edit)
    assert vault.refresh()[0]["status"] == "error"
    assert file.read_text(encoding="utf-8") == "Правка во время обновления"
    assert vault.load() == original_state


def test_guarded_pricing_publish_recovers_accepted_response_in_same_file(tmp_path):
    from tools.tests.test_editorial_pricing_adapter import desired
    vault, api, file = legacy_pricing_fixture(tmp_path)
    vault.refresh()
    file.write_text(desired(vault.read(vault.load()["items"]["pricing:active"])), encoding="utf-8")
    api.lose = "publish"
    assert vault.publish(["pricing:active"])[0]["status"] == "published"
    assert vault.status()[0]["status"] == "clean"
    count = sum(call[0] != "GET" for call in api.calls)
    assert vault.publish(["pricing:active"])[0]["status"] == "clean"
    assert sum(call[0] != "GET" for call in api.calls) == count


def test_missing_active_prices_never_replace_existing_working_file(tmp_path):
    vault, api, file = legacy_pricing_fixture(tmp_path)
    original = file.read_text(encoding="utf-8")
    original_state = vault.load()
    api.draft, api.active = api.active, None
    api.draft["status"] = "draft"
    assert vault.refresh()[0]["status"] == "error"
    assert file.read_text(encoding="utf-8") == original
    assert vault.load() == original_state
    assert all(call[0] == "GET" for call in api.calls)


def test_refresh_keeps_local_draft_and_marks_server_conflict(tmp_path):
    vault, api, file = vault_fixture(tmp_path)
    file.write_text("Моя правка", encoding="utf-8")
    api.text, api.version = "Правка на сервере", 2
    assert vault.refresh()[0]["status"] == "conflict"
    assert file.read_text(encoding="utf-8") == "Моя правка"
    assert vault.status()[0]["status"] == "conflict"


def test_refresh_updates_clean_copy_without_new_version(tmp_path):
    vault, api, file = vault_fixture(tmp_path)
    api.text, api.version = "Серверная правка", 2
    vault.refresh()
    assert file.read_text(encoding="utf-8") == api.text
    assert vault.load()["items"]["one"]["base_version"] == 2
    assert all(call[0] == "GET" for call in api.calls)


def test_refresh_does_not_overwrite_unregistered_file(tmp_path):
    vault, api, file = vault_fixture(tmp_path)
    atomic_json(vault.state_path, {"schema": 1, "items": {}})
    vault.discover = lambda: {"one": {"kind": "public", "group": "Раздел", "api_path": "/admin/api/material", "path": "Материал.md"}}
    file.write_text("Несохранённый оригинал", encoding="utf-8")
    assert vault.refresh()[0]["status"] == "error"
    assert file.read_text(encoding="utf-8") == "Несохранённый оригинал"


def test_publish_selective_and_updates_base(tmp_path):
    vault, api, file = vault_fixture(tmp_path)
    file.write_text("Правка", encoding="utf-8")
    assert vault.publish(["one"])[0]["status"] == "published"
    assert vault.status()[0]["status"] == "clean"
    assert len([c for c in api.calls if c[0] == "PUT"]) == 1
    vault.publish(["one"])
    assert len([c for c in api.calls if c[0] == "PUT"]) == 1


def test_publish_conflict_does_not_write_server(tmp_path):
    vault, api, file = vault_fixture(tmp_path)
    file.write_text("Локально", encoding="utf-8")
    api.version = 2
    assert vault.publish(["one"])[0]["status"] == "error"
    assert all(c[0] == "GET" for c in api.calls)


def test_blog_partial_save_retries_publication_without_resaving(tmp_path):
    vault, api, file = vault_fixture(tmp_path, "blog")
    file.write_text("Новый текст", encoding="utf-8")
    api.fail_publish = True
    assert vault.publish(["one"])[0]["status"] == "error"
    assert vault.status()[0]["status"] == "changed"
    api.fail_publish = False
    assert vault.publish(["one"])[0]["status"] == "published"
    assert len([c for c in api.calls if c[0] == "PATCH"]) == 1


def test_unknown_blog_save_result_refresh_preserves_pending_publication(tmp_path):
    vault, api, file = vault_fixture(tmp_path, "blog")
    file.write_text("Отправленная правка", encoding="utf-8")
    api.text, api.version, api.published = "Отправленная правка", 2, False
    vault.refresh()
    assert vault.status()[0]["status"] == "changed"
    assert vault.publish(["one"])[0]["status"] == "published"
    assert not any(c[0] == "PATCH" for c in api.calls)


def test_blog_further_edit_after_saved_draft_can_publish(tmp_path):
    vault, api, file = vault_fixture(tmp_path, "blog")
    file.write_text("Первая правка", encoding="utf-8")
    api.fail_publish = True
    assert vault.publish(["one"])[0]["status"] == "error"
    file.write_text("Вторая правка", encoding="utf-8")
    assert vault.refresh()[0]["status"] == "draft"
    api.fail_publish = False
    assert vault.publish(["one"])[0]["status"] == "published"
    assert api.text == "Вторая правка"


def test_unknown_save_then_further_local_edit_recovers_own_base(tmp_path):
    vault, api, file = vault_fixture(tmp_path, "blog")
    file.write_text("Отправленная правка", encoding="utf-8")
    original = api.request
    def lost_response(method, path, payload=None):
        result = original(method, path, payload)
        if method == "PATCH":
            raise TimeoutError("Ответ потерян после записи")
        return result
    api.request = lost_response
    assert vault.publish(["one"])[0]["status"] == "error"
    file.write_text("Продолженная правка", encoding="utf-8")
    assert vault.refresh()[0]["status"] == "draft"
    api.request = original
    assert vault.publish(["one"])[0]["status"] == "published"
    assert api.text == "Продолженная правка"


def test_update_checks_current_file_before_writing(tmp_path):
    file = tmp_path / "Материал.md"
    file.write_text("Новая правка", encoding="utf-8")
    assert not update_if_unchanged(file, "Прежний текст", "Сервер")
    assert file.read_text(encoding="utf-8") == "Новая правка"
    assert update_if_unchanged(file, "Новая правка", "Принято")
    assert not update_if_unchanged(file, None, "Не перезаписывать существующий")


def test_refresh_preserves_autosave_after_initial_read(tmp_path, monkeypatch):
    vault, api, file = vault_fixture(tmp_path)
    api.text, api.version = "Серверная версия", 2
    from tools import editorial_vault
    original = editorial_vault.update_if_unchanged
    def autosave(path, expected, replacement):
        path.write_text("Правка Obsidian", encoding="utf-8")
        return original(path, expected, replacement)
    monkeypatch.setattr(editorial_vault, "update_if_unchanged", autosave)
    assert vault.refresh()[0]["status"] == "error"
    assert file.read_text(encoding="utf-8") == "Правка Obsidian"


def test_edit_during_publish_remains_local_changed_draft(tmp_path):
    vault, api, file = vault_fixture(tmp_path)
    file.write_text("Отправлено", encoding="utf-8")
    api.edit_while_publishing = lambda: file.write_text("Ещё одна правка", encoding="utf-8")
    assert vault.publish(["one"])[0]["status"] == "published"
    assert file.read_text(encoding="utf-8") == "Ещё одна правка"
    assert vault.status()[0]["status"] == "changed"


def test_vault_blocks_outside_path_and_parallel_operation(tmp_path):
    vault, api, file = vault_fixture(tmp_path)
    with pytest.raises(VaultError):
        vault.file({"path": "../outside.md"})
    with vault.lock():
        with pytest.raises(VaultError):
            with vault.lock():
                pass


def test_public_version_marker_is_not_an_editorial_change():
    assert comparable("<!-- public-site-version: 2 -->\n\nТекст", "public") == comparable("<!-- public-site-version: 3 -->\n\nТекст", "public")


def test_public_publish_with_obsidian_final_newline_matches_server_normalization(tmp_path):
    vault, api, file = vault_fixture(tmp_path)
    file.write_text("  Новый текст\n", encoding="utf-8")
    assert vault.publish(["one"])[0]["status"] == "published"
    assert vault.status()[0]["status"] == "clean"
    vault.refresh()
    assert vault.status()[0]["status"] == "clean"


def test_selected_item_publishes_without_touching_other_changed_draft(tmp_path):
    vault, first_api, first_file = vault_fixture(tmp_path)
    second_api = FakeAPI()
    state = vault.load()
    state["items"]["two"] = {**state["items"]["one"], "path": "Второй.md", "api_path": "/admin/api/second"}
    atomic_json(vault.state_path, state)
    second_file = tmp_path / "Второй.md"
    second_file.write_text("Невыбранный черновик", encoding="utf-8")
    first_file.write_text("Выбранная правка", encoding="utf-8")
    class RoutingAPI:
        def request(self, method, path, payload=None):
            return (second_api if path.endswith("second") else first_api).request(method, path, payload)
    vault.api = RoutingAPI()
    assert vault.publish(["one"])[0]["status"] == "published"
    assert second_api.calls == []
    assert second_file.read_text(encoding="utf-8") == "Невыбранный черновик"
    assert vault.load()["items"]["two"] == state["items"]["two"]


def test_course_missing_or_stale_validation_blocks_put(tmp_path):
    vault, api, file = vault_fixture(tmp_path, "course")
    state = vault.load()
    state["items"]["one"]["format"] = "markdown"
    atomic_json(vault.state_path, state)
    file.write_text("Правка курса", encoding="utf-8")
    assert vault.publish(["one"])[0]["status"] == "error"
    assert not any(call[0] == "PUT" for call in api.calls)
    gate = vault.state_path.parent / "reviews" / "one"
    gate.parent.mkdir()
    pack = gate.with_suffix(".pack.json")
    pack.write_text("{}", encoding="utf-8")
    report = {"schema_version": "author-validation-v1", "status": "pass",
              "pack_sha256": digest("{}"), "draft_sha256": digest("Предыдущий текст")}
    gate.with_suffix(".report.json").write_text(json.dumps(report), encoding="utf-8")
    assert vault.publish(["one"])[0]["status"] == "error"
    assert not any(call[0] == "PUT" for call in api.calls)
    report["draft_sha256"] = digest("Правка курса")
    gate.with_suffix(".report.json").write_text(json.dumps(report), encoding="utf-8")
    assert vault.publish(["one"])[0]["status"] == "published"
    assert len([call for call in api.calls if call[0] == "PUT"]) == 1


def test_owner_can_publish_his_obsidian_course_edit_without_ai_reports(tmp_path):
    vault, api, file = vault_fixture(tmp_path, "course")
    state = vault.load()
    state["items"]["one"]["format"] = "markdown"
    atomic_json(vault.state_path, state)
    file.write_text("Готовая правка Сергея", encoding="utf-8")
    assert vault.publish(["one"], owner_edited=True)[0]["status"] == "published"
    assert api.text == "Готовая правка Сергея"
    assert not (vault.state_path.parent / "reviews").exists()


def test_owner_publication_preserves_the_same_server_conflict_checks(tmp_path):
    vault, api, file = vault_fixture(tmp_path, "course")
    file.write_text("Моя правка", encoding="utf-8")
    api.version = 2
    assert vault.publish(["one"], owner_edited=True)[0]["status"] == "error"
    assert not any(call[0] == "PUT" for call in api.calls)
