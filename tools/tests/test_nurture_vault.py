import copy
import json
import pytest

from tools import editorial_bot_adapter as bot
from tools.editorial_vault import Vault, atomic_json
from tools.register_nurture_vault import register


def original(code="tpl_nurture_01_tg_full"):
    return {"code": code, "title": "Название не выбрано", "content_version": 1,
            "source_markdown": "", "body_source": "", "purpose": "Цель", "writer_brief": "ТЗ",
            "media_kind": None, "editorial_status": "placeholder", "usages": []}


class API:
    def __init__(self, count=60):
        self.items = {code: original(code) for n in range(1, count + 1)
                      for variant in ("tg_full", "tg_channel", "max_full")
                      for code in [f"tpl_nurture_{n:02d}_{variant}"]}
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if path.endswith("content-audit"):
            return {"items": list(copy.deepcopy(self.items).values())}
        item = self.items[path.split("/")[-2]]
        if method == "GET":
            return copy.deepcopy(item)
        if not payload["source_markdown"].strip():
            raise ValueError("Пустой текст")
        if payload["expected_version"] != item["content_version"]:
            raise ValueError("409")
        if method == "PUT":
            item.update({name: payload[name] for name in ("source_markdown", "purpose", "writer_brief", "title")})
            item["content_version"] += 1
        return copy.deepcopy(item)


def prepared(tmp_path, count=60):
    api = API(count)
    vault = Vault(tmp_path, api)
    for code in api.items:
        path = tmp_path / bot.nurture_path(code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\ntitle: "Название не выбрано"\nstatus: placeholder\n---\n\n', encoding="utf-8")
    return vault, api


def test_register_all_drafts_preserves_owner_body_and_other_catalog_entries(tmp_path):
    vault, api = prepared(tmp_path)
    state = vault.load()
    other = {"kind": "public", "title": "Существующая статья", "group": "Статьи",
             "path": "existing.md", "base_version": 12, "base_hash": "unchanged", "conflict": True}
    state["items"]["public:existing"] = copy.deepcopy(other)
    vault.state_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(vault.state_path, state)
    (vault.root / "existing.md").write_text("Мой черновик", encoding="utf-8")
    selected = vault.root / bot.nurture_path("tpl_nurture_01_tg_full")
    selected.write_text('---\ntitle: "Мой пост"\n---\n\n**Мои слова**\n', encoding="utf-8")
    assert register(vault) == 180
    parsed = bot.parse(selected.read_text(encoding="utf-8"))
    assert parsed["source_markdown"] == "**Мои слова**\n" and parsed["title"] == "Мой пост"
    assert len(vault.load()["items"]) == 181
    assert vault.load()["items"]["public:existing"] == other
    assert (vault.root / "existing.md").read_text(encoding="utf-8") == "Мой черновик"
    assert all(method == "GET" for method, _, _ in api.calls)
    assert register(vault) == 0
    assert vault.load()["items"]["public:existing"] == other
    rows = {row["id"]: row for row in vault.status()}
    assert rows["bot:tpl_nurture_01_tg_full"]["status"] == "changed"
    assert rows["bot:tpl_nurture_02_tg_full"]["status"] == "clean"


def test_partial_inventory_cannot_register_or_overwrite_drafts(tmp_path):
    vault, api = prepared(tmp_path, 59)
    target = vault.root / bot.nurture_path("tpl_nurture_01_tg_full")
    before = target.read_bytes()
    with pytest.raises(ValueError, match="180"):
        register(vault)
    assert target.read_bytes() == before and vault.load()["items"] == {}


def test_owner_publishes_one_selected_markdown_slot_without_rule_or_other_slot_mutation(tmp_path):
    vault, api = prepared(tmp_path)
    register(vault)
    ident = "bot:tpl_nurture_03_max_full"
    item = vault.load()["items"][ident]
    path = vault.file(item)
    text = path.read_text(encoding="utf-8").replace('"title": "Название не выбрано"', '"title": "Название"')
    path.write_text(text.replace("\n\n<!-- bot-publisher", "**Полный пост**\n\n<!-- bot-publisher"), encoding="utf-8")
    untouched = copy.deepcopy(api.items["tpl_nurture_03_tg_full"])
    result = vault.publish([ident], owner_edited=True)
    assert result[0]["status"] == "published", result
    assert api.items["tpl_nurture_03_tg_full"] == untouched
    mutations = [call for call in api.calls if call[0] != "GET"]
    assert [(call[0], call[1].split("/")[-1]) for call in mutations] == [("POST", "validate"), ("PUT", "publish")]
    assert set(mutations[-1][2]) == {"body_source", "source_markdown", "title", "purpose", "writer_brief", "expected_version", "confirm"}
    assert "ЦЕЛЬ СООБЩЕНИЯ" not in path.read_text(encoding="utf-8")


def test_markdown_roundtrip_and_comparison_ignore_generated_version_but_not_title():
    data = original(); data.update(title='Название "с кавычками"', source_markdown="> Цитата\n\n**Текст**\n")
    text = bot.render(data)
    assert bot.parse(text)["source_markdown"] == data["source_markdown"]
    assert bot.normalize(text) == bot.normalize(text.replace('"version": 1', '"version": 44'))
    data["title"] = "Другое название"
    assert bot.normalize(bot.render(data)) != bot.normalize(text)


def test_refresh_preserves_dirty_file_and_marks_concurrent_server_edit_as_conflict(tmp_path):
    vault, api = prepared(tmp_path)
    register(vault)
    ident = "bot:tpl_nurture_02_tg_full"
    path = vault.file(vault.load()["items"][ident])
    before = path.read_text(encoding="utf-8").replace("\n\n<!-- bot-publisher", "Правка Сергея\n\n<!-- bot-publisher")
    path.write_text(before, encoding="utf-8")
    api.items["tpl_nurture_02_tg_full"].update(source_markdown="Правка на сервере", content_version=2)
    seeds = bot.discover(api)
    vault.discover = lambda: {ident: seeds[ident]}
    result = vault.refresh()
    assert result[0]["status"] == "conflict"
    assert path.read_text(encoding="utf-8") == before
