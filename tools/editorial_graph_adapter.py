"""Edit original sequence JSON in Obsidian; use existing version-pinned bot API."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

FLOW_CODES = ("welcome_intensive", "prepurchase_nurture")
METADATA_KEY = "_editorial_graph"
MAX_SOURCE_BYTES = 500_000


def _path(code):
    if code not in FLOW_CODES:
        raise ValueError("Редактирование этой цепочки не поддерживается")
    return f"/bot-api/sequences/{code}/source"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Повторяющееся поле JSON: " + key)
        result[key] = value
    return result


def _parse_json(source):
    return json.loads(source, object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Недопустимое число JSON: " + value)))


def parse(text):
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("Файл логики превышает 500 КБ")
    text = text.replace("\r\n", "\n").strip()
    header_code = None
    if text.startswith("---\n"):
        header = re.match(r"\A---\n(.*?)\n---\n\s*", text, re.S)
        if not header:
            raise ValueError("Повреждена служебная шапка графа")
        fields = {}
        for line in header[1].splitlines():
            key, separator, value = line.partition(":")
            if not separator or key in fields:
                raise ValueError("Повреждены поля служебной шапки графа")
            fields[key] = value.strip()
        if set(fields) != {"code", "version", "title"} or not fields["version"].isdigit():
            raise ValueError("В шапке графа нужны code, version и title")
        header_code = fields["code"]
        _path(header_code)
        text = text[header.end():]
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    data = _parse_json(text)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Неизвестный формат оригинала графа")
    sequence = data.get("sequence")
    if not isinstance(sequence, dict):
        raise ValueError("В оригинале отсутствует описание цепочки")
    _path(sequence.get("code"))
    if header_code is not None and header_code != sequence["code"]:
        raise ValueError("Код в шапке отличается от кода оригинала")
    if not isinstance(data.get("steps"), list) or not data["steps"] or not isinstance(data.get("edges"), list):
        raise ValueError("В оригинале нужны полные шаги и переходы")
    for step in data["steps"]:
        if not isinstance(step, dict) or type(step.get("position")) is not int or not isinstance(step.get("configuration"), dict):
            raise ValueError("Повреждён шаг оригинального графа")
        marker = step["configuration"].get(METADATA_KEY)
        if marker is not None and (not isinstance(marker, dict) or marker.get("owner") != "messaging.telegram.engine"
                                   or marker.get("schema_version") != 1):
            raise ValueError("Повреждена служебная метка владельца графа")
    for edge in data["edges"]:
        if not isinstance(edge, dict) or not isinstance(edge.get("from_step_key"), str) or not isinstance(edge.get("branch_key"), str) or type(edge.get("priority")) is not int:
            raise ValueError("Повреждён переход оригинального графа")
    return data


def _canonical(data):
    data = deepcopy(data)
    data["steps"].sort(key=lambda step: step["position"])
    data["edges"].sort(key=lambda edge: (edge["from_step_key"], edge["branch_key"], edge["priority"]))
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def normalize(text):
    """Compare executable originals; presentation header and inert stamp do not execute."""
    data = parse(text)
    for step in data["steps"]:
        step["configuration"].pop(METADATA_KEY, None)
    return _canonical(data)


def _revision(edition):
    version, sha = edition.get("version"), edition.get("sha256")
    if type(version) is not int or version < 1 or not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError("API вернул некорректную редакцию графа")
    return {"version": version, "sha256": sha}


def render(edition):
    data = parse(edition["source"])
    title = json.dumps(data["sequence"]["name"], ensure_ascii=False)
    return (f"---\ncode: {data['sequence']['code']}\nversion: {edition['version']}\ntitle: {title}\n---\n\n"
            + "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```\n")


def _edition(raw, code, status):
    if raw is None:
        return None
    revision = _revision(raw)
    if raw.get("status") != status:
        raise ValueError("API вернул другую стадию графа")
    data = parse(raw["source"])
    if data["sequence"]["code"] != code:
        raise ValueError("API вернул другую цепочку")
    if hashlib.sha256(_canonical(data).encode("utf-8")).hexdigest() != revision["sha256"]:
        raise ValueError("Хеш оригинала API не совпадает с его содержанием")
    if "document" in raw and _canonical(data) != _canonical(raw["document"]):
        raise ValueError("API вернул разные представления оригинала")
    text = render(raw)
    semantic = hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()
    if raw.get("semantic_sha256") != semantic:
        raise ValueError("Исполняемый хеш графа API не совпадает с оригиналом")
    first = min(data["steps"], key=lambda step: step["position"])
    marker = first["configuration"].get(METADATA_KEY, {})
    return {"version": revision, "text": text, "document": data,
            "base_published": marker.get("base_published"), "semantic_sha256": semantic}


def read(api, item):
    code = item["code"]
    raw = api.request("GET", _path(code))
    if raw.get("code") != code:
        raise ValueError("API вернул другую цепочку")
    published = _edition(raw.get("published"), code, "published")
    if published is None:
        raise ValueError("У цепочки нет опубликованного оригинала; черновик не подставляется вместо него")
    draft = _edition(raw.get("draft"), code, "draft")
    return {"version": published["version"], "text": published["text"],
            "title": published["document"]["sequence"]["name"], "format": "json-fence",
            "editorial_owned": raw.get("editorial_owned") is True,
            "draft": draft, "draft_base": draft["base_published"] if draft else None,
            "pending_draft": draft["version"] if draft else None}


def discover(api):
    result = {}
    for code in FLOW_CODES:
        remote = read(api, {"code": code})
        result["graph:" + code] = {"kind": "graph", "code": code, "title": remote["title"],
            "group": "Логика бота", "path": f"Логика бота/{code}.md", "api_path": _path(code)}
    return result


def _matching_draft(remote, requested):
    draft = remote.get("draft")
    if draft and (normalize(draft["text"]) != requested or draft["base_published"] != remote["version"]):
        raise ValueError("На сервере другой или устаревший черновик графа; объедините правки через Codex")
    return draft


def publish(api, item, text, remote):
    data = parse(text)
    code = item["code"]
    if data["sequence"]["code"] != code:
        raise ValueError("Код оригинала не совпадает с выбранной цепочкой")
    requested = normalize(text)
    current = read(api, item)
    # Recovery checks exact accepted semantics, not arithmetic on version counters.
    if current["editorial_owned"] and normalize(current["text"]) == requested:
        return current
    if current["version"] != remote["version"]:
        raise ValueError("Опубликованный граф изменился; получите обновления перед отправкой")
    draft = _matching_draft(current, requested)
    if draft is None:
        try:
            api.request("PUT", _path(code) + "/draft", {
                "source": json.dumps(data, ensure_ascii=False, indent=2),
                "expected_published": current["version"], "expected_draft": None,
            })
        except Exception:
            recovered = read(api, item)
            if recovered["editorial_owned"] and normalize(recovered["text"]) == requested:
                return recovered
            if recovered["version"] != current["version"] or _matching_draft(recovered, requested) is None:
                raise
        current_after_save = read(api, item)
        if current_after_save["version"] != current["version"]:
            raise ValueError("Опубликованный граф изменился при сохранении черновика")
        draft = _matching_draft(current_after_save, requested)
        if draft is None:
            raise ValueError("Сервер не подтвердил сохранение черновика")
    try:
        api.request("POST", _path(code) + "/publish", {
            "expected_published": current["version"], "expected_draft": draft["version"],
        })
    except Exception:
        recovered = read(api, item)
        if recovered["editorial_owned"] and normalize(recovered["text"]) == requested:
            return recovered
        raise
    verified = read(api, item)
    if not verified["editorial_owned"] or normalize(verified["text"]) != requested:
        raise ValueError("Проверка опубликованного оригинала не совпала; получите обновления")
    return verified
