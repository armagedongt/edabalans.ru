"""Bind the agreed originals to the existing vault; never start the mailing."""
from pathlib import Path
import argparse
import copy
import json
import re

from tools.editorial_vault import Vault, DEFAULT_ROOT, atomic_json, comparable, digest, update_if_unchanged
from tools import editorial_bot_adapter as bot

BASE = "Рассылка бота"
VARIANTS = {"tg_full":"Telegram — полный", "tg_channel":"Telegram — в канал", "max_full":"MAX"}
ENTRY_NAMES = {"navigation":"Навигация", "first_video":"Первое видео", "repeat_video":"Повторное видео", "owned":"Ответ покупателю", "percent_unread":"1% — не дочитал", "percent_read":"1% — дочитал", "second_belly":"Второй живот"}
ENTRY_SOURCES = {"navigation":"00 — Навигация.md", "first_video":"01 — Первое видео.md", "repeat_video":"02 — Повторное видео.md", "percent_unread":"05 — 12 часов — На один процент лучше.md", "percent_read":"05 — 12 часов — На один процент лучше.md", "second_belly":"002 — Второй живот в подарок!.md"}


def draft_body(path):
    text = path.read_text(encoding="utf-8")
    return re.sub(r"\n*<!-- bot-editorial-metadata\n.*?-->\s*\Z", "", text.replace("\r\n","\n"), flags=re.S).rstrip()+"\n"


def connect(vault):
    source_dir = vault.root / "Черновики/Новая рассылка — редактура"
    payload = {"confirm":True, "sources":{}, "families":{"1":"pyramid_weight_loss"}}
    donor = source_dir / "Telegram" / ENTRY_SOURCES["second_belly"]
    if donor.is_file():
        match = re.search(r"(?m)^source_code: (.+)$", donor.read_text(encoding="utf-8"))
        if match:
            payload["sources"] = {f"tpl_onepage_second_belly_{platform}":match[1].strip() for platform in ("tg","max")}
    vault.api.request("POST", "/bot-api/onepage-campaign/prepare", payload)
    originals = {item["code"]:item for item in vault.api.request("GET", "/bot-api/content-audit")["items"] if item.get("code")}
    with vault.lock():
        state = vault.load()
        planned = []
        index = ["# Рассылка бота", "", "[Инструкция](<Инструкция.md>) · [Банк готовых текстов](<../Черновики/Новая рассылка — редактура/Редактировать здесь.md>)", "", "## Вход и первые часы", "", "| Пост | Telegram | MAX |", "|---|---|---|"]
        for name, title in ENTRY_NAMES.items():
            links = []
            for platform, folder in (("tg","Telegram"),("max","MAX")):
                code = f"tpl_onepage_{name}_{platform}"
                raw = copy.deepcopy(originals[code])
                raw["title"] = title
                source = source_dir / ("Telegram" if platform=="tg" else "MAX") / ENTRY_SOURCES.get(name, "missing.md")
                if name == "second_belly" and not source.is_file():
                    source = source_dir / "Telegram" / ENTRY_SOURCES[name]
                if source.is_file():
                    raw["source_markdown"] = draft_body(source)
                elif name=="owned" and raw.get("source_markdown") is None:
                    readable=re.sub(r"</?(?:b|strong)>","**",raw["body_source"])
                    readable=re.sub(r"</?(?:i|em)>","*",readable)
                    if not re.search(r"</?[a-zA-Z]",readable):
                        raw["source_markdown"]=readable
                path = f"{BASE}/{folder}/Вход — {title}.md"
                planned.append((code, path, raw))
                links.append(f"[{folder}](<{folder}/Вход — {title}.md>)")
            index.append(f"| {title} | {' | '.join(links)} |")
        index += ["", "## 60 позиций", "", "| Номер | Время от первого видео | Telegram — полный | Telegram — в канал | MAX |", "|---|---|---|---|---|"]
        for n in range(1,61):
            links=[]
            for variant, folder in VARIANTS.items():
                code=f"tpl_nurture_{n:02d}_{variant}"
                raw=copy.deepcopy(originals[code])
                old=state["items"].get("bot:"+code)
                if old:
                    parsed=bot.parse(vault.file(old).read_text(encoding="utf-8"))
                    raw["source_markdown"] = parsed["source_markdown"].strip() or "[[SKIP]]"
                    raw["title"]=parsed["title"]
                else:
                    raw["source_markdown"]=raw.get("source_markdown") or "[[SKIP]]"
                raw["family_id"]="pyramid_weight_loss" if n==1 else f"slot_{n:02d}"
                path=f"{BASE}/{folder}/Пост {n:02d}.md"
                planned.append((code,path,raw))
                links.append(f"[{folder}](<{folder}/Пост {n:02d}.md>)")
            hour=12+n*12 if n<=8 else 120+(n-9)*24
            index.append(f"| {n:02d} | +{hour} ч | {' | '.join(links)} |")
        for code,path,working in planned:
            destination=vault.root/path
            if destination.exists():
                # A later invocation never replaces edited originals.
                if state["items"].get("bot:"+code,{}).get("path")==path:
                    continue
                if bot.parse(destination.read_text(encoding="utf-8"))["code"]!=code:
                    raise ValueError("В существующем файле другой код: "+path)
            destination.parent.mkdir(parents=True,exist_ok=True)
            if not destination.exists() and not update_if_unchanged(destination,None,bot.render(working)):
                raise ValueError("Файл появился во время подготовки: "+path)
            raw=originals[code]
            state["items"]["bot:"+code]={"kind":"bot", "code":code, "title":working["title"], "group":BASE,
                "path":path, "api_path":f"/bot-api/content/{code}/authoring", "base_version":raw["content_version"],
                "base_hash":digest(comparable(bot.render(raw),"bot")), "format":"telegram_markdown" if working.get("source_markdown") is not None else "telegram_html", "conflict":False}
            atomic_json(vault.state_path,state)
        (vault.root/BASE/"Порядок.md").write_text("\n".join(index)+"\n",encoding="utf-8")
        vault.catalog(state)
    return {"status":"connected", "files":len(planned), "live":False, "pool_started":False}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=DEFAULT_ROOT)
    args=parser.parse_args()
    print(json.dumps(connect(Vault(args.root)),ensure_ascii=False,indent=2))
