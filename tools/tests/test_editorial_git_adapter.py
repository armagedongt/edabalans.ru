import hashlib

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
