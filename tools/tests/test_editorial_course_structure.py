from copy import deepcopy
import pytest
from tools.editorial_vault import Vault, digest
from tools.editorial_course_structure import run


class API:
    def __init__(self):
        self.version = 1
        self.manifest = {"days": [{"number": 1, "steps": [{"id": "a"}, {"id": "b"}]}]}
        self.calls = []
        self.source = None
        self.lost = False
        self.during = None

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET" and "/materials/" in path:
            return {"version": 1, "source_format": "markdown", "source_content": self.source,
                    "html": "<p>Статья</p>", "title": "Новая"}
        if method == "GET":
            return {"active": {"version": self.version, "manifest": deepcopy(self.manifest)}}
        operation = payload["operation"]
        proposed = deepcopy(self.manifest)
        if operation["type"] == "reorder":
            proposed["days"][0]["steps"] = [{"id": ident} for ident in operation["ids"]]
        else:
            proposed["days"][0]["steps"].append({"id": operation["id"]})
        proposed["minimum_required_structure_revision"] = self.version + 1
        if path.endswith("/preview"):
            if self.during:
                self.during()
            return {"diff": "Проверенная перестановка", "manifest": proposed}
        assert payload["expected_version"] == self.version
        self.manifest, self.version = proposed, self.version + 1
        self.source = operation.get("content")
        if self.lost:
            raise TimeoutError("Ответ потерян")
        return {"version": self.version, "changed": True}


@pytest.fixture
def editor(tmp_path):
    api = API()
    vault = Vault(tmp_path, api)
    vault.state_path.parent.mkdir()
    refreshes = []
    vault.refresh = lambda ids: refreshes.extend(ids) or []
    return vault, api, refreshes


def reorder():
    return {"course_code": "masterclass-21", "expected_version": 1,
            "operation": {"type": "reorder", "unit": 1, "ids": ["b", "a"]}}


def test_preview_has_no_write_apply_checks_exact_manifest_and_refreshes_only_names(editor):
    vault, api, refreshed = editor
    result = run(vault, reorder())
    assert result["status"] == "preview" and api.version == 1
    assert not vault.state_path.exists() and refreshed == []
    result = run(vault, reorder(), apply=True)
    assert result["version"] == 2
    assert refreshed == ["names:masterclass-21"]


def test_lost_response_recovers_without_repeating_structure_edit(editor):
    vault, api, refreshed = editor
    api.lost = True
    with pytest.raises(TimeoutError):
        run(vault, reorder(), apply=True)
    assert api.version == 2
    assert run(vault, reorder(), apply=True)["status"] == "recovered"
    assert len([call for call in api.calls if call[1].endswith("/apply")]) == 1


def test_add_uses_same_canonical_file_preserves_new_draft_and_records_remote_base(editor):
    vault, api, refreshed = editor
    relative = "Курсы/masterclass-21/new.md"
    file = vault.root / relative
    file.parent.mkdir(parents=True)
    file.write_text("Авторский текст.\n", encoding="utf-8")
    config = {"course_code": "masterclass-21", "expected_version": 1,
              "operation": {"type": "add_article", "unit": 1, "id": "new", "title": "Новая",
                            "required": False, "required_for_existing": False, "content_file": relative}}
    api.lost = True
    with pytest.raises(TimeoutError):
        run(vault, config, apply=True, owner_edited=True)
    file.write_text("Моя следующая правка.\n", encoding="utf-8")
    assert run(vault, config, apply=True, owner_edited=True)["status"] == "recovered"
    item = vault.load()["items"]["course:masterclass-21:new"]
    assert item["path"] == relative
    assert item["base_hash"] == digest("Авторский текст.\n")
    assert file.read_text(encoding="utf-8") == "Моя следующая правка.\n"
    assert refreshed == ["names:masterclass-21", "course:masterclass-21:new"]


def test_autosave_during_preview_and_wrong_file_path_abort_apply(editor):
    vault, api, _ = editor
    relative = "Курсы/masterclass-21/new.md"
    file = vault.root / relative
    file.parent.mkdir(parents=True)
    file.write_text("Начальный текст", encoding="utf-8")
    config = {"course_code": "masterclass-21", "expected_version": 1,
              "operation": {"type": "add_article", "unit": 1, "id": "new", "title": "Новая",
                            "required": False, "required_for_existing": False, "content_file": relative}}
    api.during = lambda: file.write_text("Одновременная правка", encoding="utf-8")
    with pytest.raises(Exception, match="изменены"):
        run(vault, config, apply=True, owner_edited=True)
    assert api.version == 1
    assert not any(call[1].endswith("/apply") for call in api.calls)
    config["operation"]["content_file"] = "копия.md"
    with pytest.raises(Exception, match="постоянном файле"):
        run(vault, config, apply=True, owner_edited=True)
