"""Lossless Telegram HTML working files for existing editable bot slots.

The .md extension lets Obsidian show the same working file. Its body is the
original Telegram HTML, not site Markdown; publication performs no translation.
"""
from __future__ import annotations

import re
from urllib.parse import quote


CODE = re.compile(r"[a-zA-Z0-9_-]+")
PURPOSE = "ЦЕЛЬ СООБЩЕНИЯ"
BRIEF = "ТЗ ПИСАТЕЛЮ"
CONTEXT = "КОНТЕКСТ В ГРАФЕ"


def _path(code, suffix="authoring"):
    if not isinstance(code, str) or not CODE.fullmatch(code):
        raise ValueError("Недопустимый код сообщения")
    return f"/bot-api/content/{quote(code, safe='')}/{suffix}"


def discover(api):
    result = {}
    for item in api.request("GET", "/bot-api/content-audit")["items"]:
        code = item.get("code")
        if not code or item.get("editorial_status") == "missing_content":
            continue
        path = _path(code)
        result["bot:" + code] = {
            "kind": "bot", "code": code, "title": item["title"],
            "group": "Сообщения бота", "path": f"Сообщения бота/{code}.md",
            "api_path": path, "usages": item.get("usages", []),
            "allowed_variables": item.get("allowed_variables", []),
            "media_kind": item.get("media_kind"), "media_path": item.get("media_path"),
        }
    return result


def render(item):
    _path(item["code"])
    context = "\n".join(
        f"- {usage.get('module', 'модуль')} · {usage.get('previous', '—')} → {usage.get('step', 'сообщение')} → {usage.get('next', '—')}"
        for usage in item.get("usages", [])
    ) or "- Место использования не найдено"
    for name in ("purpose", "writer_brief"):
        if "-->" in item[name]:
            raise ValueError("Служебное поле содержит закрытие HTML-комментария")
    return (
        "---\n"
        f"code: {item['code']}\nversion: {item['content_version']}\n"
        f"title: {item.get('title', '').replace(chr(10), ' ').replace(chr(13), ' ')}\n"
        f"editorial_status: {item.get('editorial_status', '')}\n"
        f"media_kind: {item.get('media_kind') or ''}\n---\n\n"
        f"<!-- {PURPOSE}\n{item['purpose']}\n-->\n\n"
        f"<!-- {BRIEF}\n{item['writer_brief']}\n-->\n\n"
        f"<!-- {CONTEXT}\n{context}\n-->\n\n"
        + item["body_source"]
    )


def parse(text):
    text = text.replace("\r\n", "\n")
    header = re.match(r"\A---\n(.*?)\n---\n\n", text, re.S)
    if not header:
        raise ValueError("Повреждена служебная шапка сообщения")
    fields = {}
    for line in header[1].splitlines():
        key, separator, value = line.partition(":")
        if not separator or key in fields:
            raise ValueError("Повреждены поля служебной шапки")
        fields[key] = value.strip()
    if not {"code", "version", "media_kind"} <= fields.keys():
        raise ValueError("В шапке нужны code, version и media_kind")
    _path(fields["code"])
    if not fields["version"].isdigit() or int(fields["version"]) < 1:
        raise ValueError("Некорректная версия сообщения")
    remaining = text[header.end():]
    sections = {}
    for name in (PURPOSE, BRIEF, CONTEXT):
        section = re.match(r"\A<!-- " + re.escape(name) + r"\n(.*?)\n-->\n\n", remaining, re.S)
        if not section:
            raise ValueError("Повреждён служебный раздел: " + name)
        sections[name] = section[1]
        remaining = remaining[section.end():]
    # Existing photo/video/voice originals may have no caption. The server,
    # using its real immutable media fields, remains the publication authority.
    if not remaining.strip() and fields["media_kind"] not in {"photo", "video", "video_note", "voice"}:
        raise ValueError("Пустой текст допустим только у сообщения с медиа")
    return {
        "code": fields["code"], "purpose": sections[PURPOSE],
        "writer_brief": sections[BRIEF], "body_source": remaining,
    }


def normalize(text):
    parsed = parse(text)
    parsed["purpose"] = parsed["purpose"].strip()
    parsed["writer_brief"] = parsed["writer_brief"].strip()
    return tuple(parsed[name] for name in ("code", "purpose", "writer_brief", "body_source"))


def read(api, item):
    raw = api.request("GET", _path(item["code"]))
    if raw["code"] != item["code"]:
        raise ValueError("API вернул другое сообщение")
    return {"version": raw["content_version"], "text": render(raw), "title": raw["title"],
            "format": "telegram_html", "usages": raw.get("usages", []),
            "allowed_variables": raw.get("allowed_variables", [])}


def publish(api, item, text, expected_version):
    parsed = parse(text)
    if parsed["code"] != item["code"]:
        raise ValueError("Код в файле не совпадает с выбранным сообщением")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1:
        raise ValueError("Для публикации нужна известная версия сообщения")
    payload = {key: value for key, value in parsed.items() if key != "code"}
    payload["expected_version"] = expected_version
    api.request("POST", _path(item["code"], "validate"), payload)
    api.request("PUT", _path(item["code"], "publish"), {**payload, "confirm": True})
    remote = read(api, item)
    if remote["version"] != expected_version + 1 or normalize(remote["text"]) != normalize(text):
        raise ValueError("Серверная редакция отличается; получите обновления перед повторной публикацией")
    return remote
