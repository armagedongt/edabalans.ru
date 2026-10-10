"""One-time bind of existing 180 drafts; never publish or start runs."""
from pathlib import Path
import argparse
import json
import re

from tools.editorial_vault import Vault, DEFAULT_ROOT, atomic_json, comparable, digest, update_if_unchanged
from tools.editorial_bot_adapter import NURTURE_CODE, nurture_path, render


def register(vault):
    with vault.lock():
        state = vault.load()
        originals = {item["code"]: item for item in vault.api.request("GET", "/bot-api/content-audit")["items"]
                     if NURTURE_CODE.fullmatch(item.get("code") or "")}
        slots = {"bot:" + code: {"kind": "bot", "code": code, "group": "Рассылка — 60 постов",
                                "title": item["title"], "path": nurture_path(code)}
                 for code, item in originals.items()}
        if len(slots) != 180:
            raise ValueError("Нужны все 180 серверных редакционных слотов; локальные файлы не изменены")
        prepared = []
        for ident, item in slots.items():
            if ident in state["items"]:
                continue
            original = originals[item["code"]]
            if original.get("source_markdown") is None:
                raise ValueError("У слота нет Markdown-оригинала: " + item["code"])
            remote = {"version": original["content_version"], "text": render(original)}
            path = vault.file(item)
            text = path.read_text(encoding="utf-8")
            header = re.match(r"\A---\r?\n.*?\r?\n---\r?\n\r?\n", text, re.S)
            if not header:
                raise ValueError("Повреждена шапка: " + str(path))
            title = re.search(r"(?m)^title: (.+)$", text[:header.end()])
            if not title:
                raise ValueError("Нет названия: " + str(path))
            title_text = json.loads(title[1]) if title[1].startswith('"') else title[1]
            source = text[header.end():]
            if not source.strip():
                source = ""
            replacement = render({"code": item["code"], "content_version": remote["version"],
                                  "title": title_text, "source_markdown": source})
            item.update(base_version=remote["version"], base_hash=digest(comparable(remote["text"], "bot")),
                        format="telegram_markdown", conflict=False)
            prepared.append((ident, item, path, text, replacement))
        for ident, item, path, before, replacement in prepared:
            if not update_if_unchanged(path, before, replacement):
                raise ValueError("Файл изменён во время регистрации, правки сохранены: " + str(path))
            state["items"][ident] = item
            atomic_json(vault.state_path, state)
        vault.catalog(state)
        return len(prepared)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    print("Registered:", register(Vault(args.root)))
