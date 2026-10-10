import pytest
from tools.editorial_vault import Vault, atomic_json, digest


class API:
    def __init__(self):
        self.text = "<p>Авторский текст.</p>"
        self.version = 1
        self.format = "html"
        self.calls = []
        self.lost_response = False
        self.edit_during = None

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path.endswith("/markdown"):
            if method == "GET":
                return {"already_markdown": self.format == "markdown", "expected_version": self.version,
                        "html_sha256": digest(self.text), "markdown": "Авторский текст.\n"}
            assert payload["expected_version"] == self.version
            self.text, self.format, self.version = "Авторский текст.\n", "markdown", self.version + 1
            if self.edit_during:
                self.edit_during()
            if self.lost_response:
                raise TimeoutError("Ответ потерян")
            return {}
        return {"version": self.version, "source_content": self.text, "source_format": self.format,
                "html": "<p>Авторский текст.</p>", "title": "Статья"}


@pytest.fixture
def vault(tmp_path):
    api = API()
    vault = Vault(tmp_path, api)
    vault.state_path.parent.mkdir()
    file = tmp_path / "same.md"
    file.write_text(api.text, encoding="utf-8")
    item = {"kind": "course", "path": "same.md", "format": "html", "base_hash": digest(api.text),
            "base_version": 1, "api_path": "/admin/api/courses/calories/materials/ordinary"}
    atomic_json(vault.state_path, {"schema": 1, "items": {"one": item}})
    return vault, api, file


def test_preview_is_read_only_apply_updates_the_same_file_and_repeat_is_noop(vault):
    vault, api, file = vault
    assert vault.convert_markdown(["one"])[0]["status"] == "preview"
    assert api.version == 1 and file.read_text(encoding="utf-8") == api.text
    assert vault.convert_markdown(["one"], apply=True)[0]["status"] == "converted"
    assert file.read_text(encoding="utf-8") == "Авторский текст.\n"
    assert vault.status()[0]["status"] == "clean"
    assert vault.convert_markdown(["one"], apply=True)[0]["status"] == "clean"
    assert api.version == 2


def test_lost_response_recovers_without_second_version(vault):
    vault, api, file = vault
    api.lost_response = True
    assert vault.convert_markdown(["one"], apply=True)[0]["status"] == "error"
    assert file.read_text(encoding="utf-8").startswith("<p>")
    assert vault.convert_markdown(["one"], apply=True)[0]["status"] == "converted"
    assert api.version == 2


def test_existing_or_concurrent_obsidian_draft_is_never_overwritten(vault):
    vault, api, file = vault
    file.write_text("Мой черновик", encoding="utf-8")
    assert vault.convert_markdown(["one"], apply=True)[0]["status"] == "error"
    assert api.calls == []
    file.write_text(api.text, encoding="utf-8")
    api.edit_during = lambda: file.write_text("Моя новая правка", encoding="utf-8")
    assert vault.convert_markdown(["one"], apply=True)[0]["status"] == "error"
    assert file.read_text(encoding="utf-8") == "Моя новая правка"


def test_changed_server_or_unsupported_original_is_not_converted(vault):
    vault, api, file = vault
    api.version += 1
    assert vault.convert_markdown(["one"], apply=True)[0]["status"] == "error"
    assert all(call[0] == "GET" for call in api.calls)
    state = vault.load()
    state["items"]["one"]["unsupported"] = True
    atomic_json(vault.state_path, state)
    api.calls.clear()
    assert vault.convert_markdown(["one"], apply=True)[0]["status"] == "error"
    assert api.calls == []
