"""Working copies of actual catalog/structure originals, through guarded APIs."""
from __future__ import annotations

from copy import deepcopy
import json
import re


PRODUCT_FIELDS = {"shortName", "fullName", "descriptor", "status", "marketing"}
TARIFF_FIELDS = {"name", "descriptor", "status"}
SUPPORTED_COURSES = {"masterclass-21", "calories"}


def discover(api):
    items = {"product:core": {
        "id": "product:core", "kind": "catalog", "title": "Названия и описания продуктов и тарифов",
        "group": "Каталог", "path": "Каталог/Продукты и тарифы.md",
        "api_path": "/admin/api/product-catalog",
    }, "pricing:active": {
        "id": "pricing:active", "kind": "pricing", "title": "Действующий каталог цен",
        "group": "Каталог", "path": "Каталог/Цены.md", "api_path": "/admin/api/pricing",
        "unsupported": True,
    }}
    for course in api.request("GET", "/admin/api/courses")["courses"]:
        code = course["code"]
        if code not in SUPPORTED_COURSES:
            continue
        ident = "names:" + code
        items[ident] = {"id": ident, "kind": "names", "title": "Названия — " + course["name"],
            "group": code, "path": f"Курсы/{code}/Названия.md",
            "api_path": f"/admin/api/courses/{code}/structure"}
    return items


def render(item, version, payload):
    explanation = {
        "catalog": "Меняются названия, описания, маркетинговый текст и статус. Коды, состав и порядок сохраняются.",
        "names": "Меняются только title дней/этапов и title/label материалов. Добавление и перестановка — через Codex.",
        "pricing": "Оригинал действующей версии цен для чтения. Изменение и публикация — отдельной командой через Codex.",
    }[item["kind"]]
    return (f"---\nid: {item['id']}\nversion: {version}\n---\n\n# {item['title']}\n\n"
            + explanation + "\n\n```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```\n")


def parse(text):
    text = text.replace("\r\n", "\n")
    header = re.match(r"\A---\nid: ([a-z0-9:-]+)\nversion: (\d+)\n---\n", text)
    blocks = list(re.finditer(r"(?m)^```json\n(.*?)\n```\s*$", text, re.S))
    if not header or len(blocks) != 1:
        raise ValueError("Нужны исходная шапка и один JSON-блок оригинала")
    ident = header[1]
    if ident not in {"product:core", "pricing:active", *("names:" + code for code in SUPPORTED_COURSES)}:
        raise ValueError("Неизвестный оригинал каталога")
    try:
        payload = json.loads(blocks[0][1])
    except json.JSONDecodeError as exc:
        raise ValueError("JSON оригинала повреждён: " + str(exc)) from exc
    if not isinstance(payload, dict):
        raise ValueError("Оригинал должен быть JSON-объектом")
    return ident, payload


def normalized_payload(ident, payload):
    result = deepcopy(payload)
    def objects(value):
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ValueError("Список оригинала должен содержать JSON-объекты")
        return value
    if ident == "product:core":
        for key, fields in (("products", PRODUCT_FIELDS), ("tariffs", TARIFF_FIELDS)):
            for item in objects(result.get(key, [])):
                for field in fields & item.keys():
                    item[field] = str(item.get(field) or "").strip()
    elif ident.startswith("names:"):
        units = result.get("days" if ident == "names:masterclass-21" else "stages", [])
        for unit in objects(units):
            if "title" in unit:
                unit["title"] = str(unit.get("title") or "").strip()
            for step in objects(unit.get("steps", [])):
                for field in ("title", "label"):
                    if field in step:
                        step[field] = str(step.get(field) or "").strip()
    return result


def normalize(text):
    ident, payload = parse(text)
    return json.dumps({"id": ident, "payload": normalized_payload(ident, payload)},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read(api, item):
    raw = api.request("GET", item["api_path"])
    if item["kind"] == "pricing":
        active = [version for version in raw["versions"] if version["status"] == "active"]
        if len(active) > 1:
            raise ValueError("API вернул несколько действующих версий цен")
        payload = active[0] if active else {"status": "not_published", "entries": []}
        version = payload.get("version_number", 0)
        return {"version": version, "title": item["title"], "text": render(item, version, payload),
                "unsupported": True, "live_consumption_enabled": raw["live_consumption_enabled"]}
    active = raw["active"]
    return {"version": active["version"], "title": item["title"],
            "text": render(item, active["version"], active["manifest"])}


def _preserve_fields(proposed, current, allowed):
    if not isinstance(proposed, dict) or proposed.keys() != current.keys():
        raise ValueError("Набор полей оригинала нельзя менять")
    for key in current:
        if key not in allowed and proposed[key] != current[key]:
            raise ValueError("Системное поле или порядок нельзя менять: " + key)
        if key in allowed and isinstance(current[key], str) and not isinstance(proposed[key], str):
            raise ValueError("Название или текст должен быть строкой: " + key)


def validate_changes(ident, proposed, current):
    if ident == "product:core":
        _preserve_fields(proposed, current, {"products", "tariffs"})
        for group, allowed in (("products", PRODUCT_FIELDS), ("tariffs", TARIFF_FIELDS)):
            if not isinstance(proposed[group], list) or len(proposed[group]) != len(current[group]):
                raise ValueError("Добавление и удаление продуктов — через Codex")
            for new, old in zip(proposed[group], current[group], strict=True):
                _preserve_fields(new, old, allowed)
    else:
        key = "days" if ident == "names:masterclass-21" else "stages"
        _preserve_fields(proposed, current, {key})
        if not isinstance(proposed[key], list) or len(proposed[key]) != len(current[key]):
            raise ValueError("Число дней/этапов нельзя менять")
        for new, old in zip(proposed[key], current[key], strict=True):
            _preserve_fields(new, old, {"title", "steps"})
            if not isinstance(new["steps"], list) or len(new["steps"]) != len(old["steps"]):
                raise ValueError("Добавление и удаление материалов — через Codex")
            for step, old_step in zip(new["steps"], old["steps"], strict=True):
                _preserve_fields(step, old_step, {"title", "label"})


def publish(api, item, text, expected_version):
    if item["kind"] == "pricing":
        raise ValueError("Цены публикуются отдельным workflow через Codex; общий издатель не меняет цены")
    ident, proposed = parse(text)
    if ident != item["id"]:
        raise ValueError("ID файла не совпадает с выбранным оригиналом")
    remote = read(api, item)
    if remote["version"] != expected_version:
        raise ValueError("Конфликт версии: получите обновления с сервера")
    _, current = parse(remote["text"])
    validate_changes(ident, proposed, current)
    proposed = normalized_payload(ident, proposed)
    api.request("PUT", item["api_path"], {"expected_version": expected_version,
        "payload" if item["kind"] == "catalog" else "manifest": proposed})
    confirmed = read(api, item)
    if confirmed["version"] not in (expected_version, expected_version + 1) or normalize(confirmed["text"]) != normalize(text):
        raise ValueError("Серверный оригинал отличается; проверьте обновления перед повтором")
    return confirmed
