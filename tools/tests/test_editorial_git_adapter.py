import hashlib

import pytest

from tools.tests.test_editorial_vault import vault_fixture


def git_fixture(tmp_path):
    vault, api, file = vault_fixture(tmp_path, "git")
    api.version = "a" * 40
    api.runtime_text = api.text
    api.draft = None
    state = vault.load()
    state["items"]["one"]["base_version"] = api.version
    from tools.editorial_vault import atomic_json
    atomic_json(vault.state_path, state)

    def request(method, path, payload=None):
        api.calls.append((method, path, payload))
        if method == "GET":
            return {"main": {"sha": api.version, "content": api.text}, "draft": api.draft,
                    "draft_base_main_sha": "a" * 40 if api.draft else None,
                    "runtime_source": {"sha256": hashlib.sha256(api.runtime_text.encode()).hexdigest()}}
        assert payload["expected_main_sha"] == api.version
        if method == "PUT":
            api.draft = {"sha": "d" * 40, "content": payload["content"]}
            return {"sha": api.draft["sha"]}
        assert payload["expected_draft_sha"] == api.draft["sha"]
        api.text, api.version = api.draft["content"], "b" * 40
        api.draft = None
        return {"deployment": "queued"}
    api.request = request
    return vault, api, file


def test_git_waits_for_runtime_and_never_resubmits_accepted_content(tmp_path):
    vault, api, file = git_fixture(tmp_path)
    file.write_text("Новая редакция", encoding="utf-8")
    assert vault.publish(["one"])[0]["status"] == "queued"
    assert vault.status()[0]["status"] == "changed"
    assert vault.publish(["one"])[0]["status"] == "queued"
    assert len([c for c in api.calls if c[0] == "POST"]) == 1
    api.runtime_text = api.text
    vault.refresh()
    assert vault.status()[0]["status"] == "clean"
    assert file.read_text(encoding="utf-8") == "Новая редакция"


def test_git_never_replaces_other_server_draft(tmp_path):
    vault, api, file = git_fixture(tmp_path)
    file.write_text("Моя редакция", encoding="utf-8")
    api.draft = {"sha": "d" * 40, "content": "Чужая редакция"}
    assert vault.publish(["one"])[0]["status"] == "error"
    assert all(c[0] == "GET" for c in api.calls)
    assert file.read_text(encoding="utf-8") == "Моя редакция"


def test_git_recovers_lost_publish_response(tmp_path):
    vault, api, file = git_fixture(tmp_path)
    file.write_text("Моя редакция", encoding="utf-8")
    original = api.request
    def lost_response(method, path, payload=None):
        result = original(method, path, payload)
        if method == "POST":
            raise TimeoutError("Ответ потерян")
        return result
    api.request = lost_response
    assert vault.publish(["one"])[0]["status"] == "error"
    api.request = original
    assert vault.publish(["one"])[0]["status"] == "queued"
    assert len([c for c in api.calls if c[0] == "POST"]) == 1


def course_git_migration_fixture(tmp_path):
    from tools.editorial_vault import atomic_json, digest
    vault, api, file = git_fixture(tmp_path)
    state = vault.load()
    item = state["items"].pop("one")
    ident = "course:masterclass-21:day-01-article-02"
    item.update(kind="course", base_version=2, base_hash=digest(api.text), unsupported=True)
    state["items"][ident] = item
    atomic_json(vault.state_path, state)
    seed = {**item, "kind": "git", "api_path": "/admin/api/editorial/masterclass/materials/day-01-article-02",
            "source_path": "content/masterclass/current/day-01.md"}
    vault.discover = lambda: {ident: seed}
    return vault, api, file, ident


@pytest.mark.parametrize("dirty", [False, True])
def test_course_git_migration_preserves_same_file_and_local_draft(tmp_path, dirty):
    vault, api, file, ident = course_git_migration_fixture(tmp_path)
    if dirty:
        file.write_text("Локальный черновик", encoding="utf-8")
    assert vault.refresh()[0]["status"] == ("draft" if dirty else "clean")
    item = vault.load()["items"][ident]
    assert item["kind"] == "git" and item["base_version"] == "a" * 40
    assert not item["unsupported"]
    assert vault.file(item) == file
    assert file.read_text(encoding="utf-8") == ("Локальный черновик" if dirty else api.text)
    assert all(call[0] == "GET" for call in api.calls)


def test_course_git_migration_remote_change_keeps_old_baseline_for_merge(tmp_path):
    vault, api, file, ident = course_git_migration_fixture(tmp_path)
    file.write_text("Локальный черновик", encoding="utf-8")
    api.text = "Новый оригинал на сервере"
    assert vault.refresh()[0]["status"] == "error"
    item = vault.load()["items"][ident]
    assert item["kind"] == "course" and item["base_version"] == 2 and item["conflict"]
    assert file.read_text(encoding="utf-8") == "Локальный черновик"


def test_course_git_migration_pending_publication_is_not_rebased(tmp_path):
    from tools.editorial_vault import atomic_json
    vault, api, file, ident = course_git_migration_fixture(tmp_path)
    state = vault.load()
    state["items"][ident]["pending_hash"] = "pending"
    atomic_json(vault.state_path, state)
    assert vault.refresh()[0]["status"] == "error"
    assert vault.load()["items"][ident]["base_version"] == 2
    assert api.calls == []


def test_course_git_migration_simultaneous_edit_keeps_original_state(tmp_path, monkeypatch):
    from tools import editorial_vault
    vault, api, file, ident = course_git_migration_fixture(tmp_path)
    def concurrent(path, expected, replacement):
        path.write_text("Изменено в Obsidian", encoding="utf-8")
        return False
    monkeypatch.setattr(editorial_vault, "update_if_unchanged", concurrent)
    assert vault.refresh()[0]["status"] == "error"
    assert vault.load()["items"][ident]["kind"] == "course"
    assert file.read_text(encoding="utf-8") == "Изменено в Obsidian"


def test_git_course_keeps_codex_writer_gate_and_owner_publish_profile(tmp_path, monkeypatch):
    from tools import publish_course_material
    vault, api, file, ident = course_git_migration_fixture(tmp_path)
    vault.refresh()
    file.write_text("Правка Сергея", encoding="utf-8")
    checks = []
    def reject(path, pack, report):
        checks.append(path)
        raise ValueError("Нужен writer report")
    monkeypatch.setattr(publish_course_material, "verify_publish_gate", reject)
    assert vault.publish([ident])[0]["status"] == "error"
    assert checks == [file] and all(c[0] == "GET" for c in api.calls)
    assert vault.publish([ident], owner_edited=True)[0]["status"] == "queued"
    assert len([c for c in api.calls if c[0] == "POST"]) == 1


def test_real_discovery_connects_server_git_profile_to_existing_file_and_publish_route(tmp_path):
    from tools.tests.test_editorial_graph_adapter import FakeGraphAPI
    from tools.tests.test_editorial_pricing_adapter import API as PricingAPI
    vault, api, file, ident = course_git_migration_fixture(tmp_path)
    graphs, pricing = FakeGraphAPI(), PricingAPI()
    original = api.request
    def request(method, path, payload=None):
        if method == "GET":
            if path == "/admin/api/public-site/content": return {"documents": []}
            if path == "/admin/api/blog/articles": return {"articles": []}
            if path == "/admin/api/courses/masterclass-21/materials":
                return {"materials": [{"step_id": "day-01-article-02", "title": "Оригинал",
                    "publication_profile": {"type": "git", "api_path": "/admin/api/editorial/masterclass/materials/day-01-article-02",
                                             "source_path": "content/masterclass/current/day-01.md"}}]}
            if path == "/admin/api/courses/calories/materials": return {"materials": []}
            if path == "/bot-api/content-audit": return {"items": []}
            if path == "/admin/api/editorial/service-emails": return {"templates": []}
            if path == "/admin/api/courses": return {"courses": []}
            if path.startswith("/bot-api/sequences/"): return graphs.request(method, path, payload)
            if path == "/admin/api/pricing": return pricing.request(method, path, payload)
            if path == "/admin/api/product-catalog": return {"active": {"version": 1, "manifest": {"products": [], "tariffs": []}}}
            if path == "/admin/api/public-site/homepage": return {"active": {"version": 1, "markdown": "Главная"}}
        return original(method, path, payload)
    api.request = request
    del vault.discover  # Exercise the actual discovery boundary, not its migration fixture seed.
    discovered = vault.discover()
    assert discovered[ident]["kind"] == "git"
    assert discovered[ident]["path"] == "Курсы/masterclass-21/day-01-article-02.md"
    # The prior registration retains its exact original path even when discovery suggests a default.
    refreshed = vault.refresh()
    assert all(r["status"] == "clean" for r in refreshed)
    assert next(r for r in refreshed if r["id"] == ident)["status"] == "clean"
    assert vault.file(vault.load()["items"][ident]) == file
    file.write_text("Правка владельца", encoding="utf-8")
    assert vault.publish([ident], owner_edited=True)[0]["status"] == "queued"
    writes = [c for c in api.calls if c[0] != "GET"]
    assert [c[1] for c in writes] == [discovered[ident]["api_path"] + "/draft", discovered[ident]["api_path"] + "/publish"]
