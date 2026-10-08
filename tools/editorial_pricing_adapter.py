"""Edit the real pricing original using its guarded draft/publication protocol."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from uuid import UUID

from tools.editorial_catalog_adapter import parse as parse_envelope

PATH = "/admin/api/pricing"
MONEY = {"regular_amount", "compare_at_amount", "sale_amount"}
ENTRY_FIELDS = {"code", "section", "name", "product_code", "stage_code", "resource_codes",
                "item_count", *MONEY, "currency", "enabled", "sort_order", "metadata"}
STAMP = "_editorial_pricing"


def valid_revision(value):
    if not isinstance(value, dict) or value.keys() != {"id", "version_number", "sha256"}:
        return False
    try:
        UUID(value["id"])
    except (ValueError, TypeError, AttributeError):
        return False
    return (type(value["version_number"]) is int and value["version_number"] > 0
            and isinstance(value["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", value["sha256"]) is not None)


def valid_stamp(value):
    return (isinstance(value, dict) and value.keys() == {"schema_version", "owner", "base_active"}
            and type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["owner"] == "platform.commerce"
            and (value["base_active"] is None or valid_revision(value["base_active"])))


def verified_version(version):
    revision = version.get("revision")
    if not valid_revision(revision):
        raise ValueError("Повреждена ревизия цен")
    original = deepcopy(version.get("source"))
    source(original)  # Validate without replacing the exact source used for its hash.
    original["entries"].sort(key=lambda row: row["code"])
    try:
        encoded = json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Повреждён оригинал цен") from exc
    if hashlib.sha256(encoded).hexdigest() != revision["sha256"]:
        raise ValueError("Оригинал цен не совпадает с hash ревизии")
    if version.get("id") != revision["id"] or version.get("version_number") != revision["version_number"]:
        raise ValueError("Идентификатор версии цен не совпадает с ревизией")
    return revision


def amount(value, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Сумма должна быть числом с максимум двумя десятичными знаками")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > 10_000_000 or number != number.quantize(Decimal("0.01")):
            raise ValueError("Сумма вне допустимого диапазона или содержит доли копейки")
    except InvalidOperation as exc:
        raise ValueError("Некорректная сумма") from exc
    return format(number, ".2f")


def source(value, *, semantic=True):
    if not isinstance(value, dict) or value.keys() != {"schema_version", "name", "note", "entries"}:
        raise ValueError("Нужен полный оригинал действующей версии цен")
    result = deepcopy(value)
    if type(result["schema_version"]) is not int or result["schema_version"] != 1:
        raise ValueError("Неизвестная схема цен")
    if not isinstance(result["name"], str) or not result["name"].strip() or len(result["name"]) > 160:
        raise ValueError("Укажите название версии цен")
    if result["note"] is not None and (not isinstance(result["note"], str) or len(result["note"]) > 10_000):
        raise ValueError("Примечание должно быть строкой или null")
    result["name"] = result["name"].strip()
    result["note"] = (result["note"] or "").strip() or None
    entries = result["entries"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 200:
        raise ValueError("Оригинал должен содержать строки цен")
    codes = set()
    for row in entries:
        if not isinstance(row, dict) or row.keys() != ENTRY_FIELDS:
            raise ValueError("Набор полей строки цены нельзя менять")
        code = row["code"]
        if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,119}", code) or code in codes:
            raise ValueError("Некорректный или повторный код цены")
        codes.add(code)
        if not isinstance(row["metadata"], dict) or not isinstance(row["resource_codes"], list) or any(not isinstance(v, str) for v in row["resource_codes"]):
            raise ValueError("Некорректные metadata или права строки цены")
        if type(row["enabled"]) is not bool:
            raise ValueError("enabled должен быть boolean")
        for field in MONEY:
            row[field] = amount(row[field], nullable=field != "sale_amount")
        for field in ("regular_amount", "compare_at_amount"):
            if row[field] is not None and Decimal(row[field]) < Decimal(row["sale_amount"]):
                raise ValueError("Обычная/зачёркнутая цена меньше цены продажи")
    first = min(entries, key=lambda row: row["code"])
    if semantic and valid_stamp(first["metadata"].get(STAMP)):
        first["metadata"].pop(STAMP)
    return result


def parse(text):
    ident, payload = parse_envelope(text)
    if ident != "pricing:active":
        raise ValueError("ID должен быть pricing:active")
    return source(payload)


def canonical(payload):
    payload = source(payload)
    payload["entries"].sort(key=lambda row: row["code"])
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Оригинал содержит некорректные JSON-данные") from exc


def normalize(text):
    return canonical(parse(text))


def render(item, version, payload):
    return (f"---\nid: pricing:active\nversion: {version}\n---\n\n# {item['title']}\n\n"
            "Меняются только суммы, название версии и примечание. Публикация активирует выбранную редакцию цен.\n\n"
            "```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```\n")


def read(api, item):
    raw = api.request("GET", PATH)
    active = [v for v in raw["versions"] if v["status"] == "active"]
    drafts = [v for v in raw["versions"] if v["status"] == "draft"]
    if len(active) > 1 or len(drafts) > 1:
        raise ValueError("Несколько действующих версий или черновиков цен")
    if not active:
        raise ValueError("Нет опубликованной версии цен; черновик не заменяет оригинал")
    current = active[0]
    revision = verified_version(current)
    if raw["active_revision"] != revision:
        raise ValueError("Повреждена ревизия действующих цен")
    if drafts:
        verified_version(drafts[0])
    if raw["draft_revision"] != (drafts[0]["revision"] if drafts else None):
        raise ValueError("Повреждена ревизия черновика цен")
    return {"version": revision, "title": item["title"], "source": current["source"],
            "text": render(item, revision["version_number"], current["source"]), "unsupported": False, "format": "pricing-json-v1",
            "base_active": current.get("base_active"), "draft": drafts[0] if drafts else None,
            "live_consumption_enabled": raw["live_consumption_enabled"]}


def validate_changes(proposed, current):
    proposed, current = source(proposed), source(current)
    for new, old in zip(proposed["entries"], current["entries"], strict=False):
        if any(json.dumps(new[key], sort_keys=True, allow_nan=False) != json.dumps(old[key], sort_keys=True, allow_nan=False)
               for key in ENTRY_FIELDS - MONEY):
            raise ValueError("Коды, порядок, права и системные поля цен менять нельзя")
    if len(proposed["entries"]) != len(current["entries"]):
        raise ValueError("Добавление и удаление строк цен — отдельная задача")


def _healthy(draft, base):
    return (draft and draft.get("authoring_ready") is True and draft.get("base_active") == base
            and valid_revision(draft.get("revision")))


def publish(api, item, text, remote):
    if item.get("id") != "pricing:active":
        raise ValueError("Выбран другой оригинал")
    desired = parse(text)
    if remote.get("unsupported") or not valid_revision(remote.get("version")):
        raise ValueError("Действующая версия цен отсутствует")
    validate_changes(desired, remote["source"])
    base = remote["version"]
    current = read(api, item)
    if current.get("unsupported"):
        raise ValueError("Действующая версия цен исчезла")
    wanted = canonical(desired)
    if current["version"] != base:
        if current.get("base_active") == base and canonical(current["source"]) == wanted:
            return current  # Exactly the requested publication already accepted.
        raise ValueError("Действующая версия цен изменилась; получите обновления")
    if canonical(current["source"]) == wanted:
        return current
    draft = current["draft"]
    if draft:
        if not _healthy(draft, base) or canonical(draft["source"]) != wanted:
            raise ValueError("Есть другой или устаревший черновик цен; объедините его через Codex")
    else:
        # A lost clone response is ambiguous: never adopt an arbitrary clone.
        draft = api.request("POST", PATH + "/drafts", {"expected_active": base, "expected_draft": None})["version"]
        verified_version(draft)
        if not _healthy(draft, base) or canonical(draft["source"]) != canonical(current["source"]):
            raise ValueError("Созданный черновик отличается от действующего оригинала")
        update = {"expected_active": base, "expected_draft": draft["revision"],
                  "name": desired["name"], "note": desired["note"],
                  "entries": [{key: row[key] for key in ("code", *sorted(MONEY), "enabled")} for row in desired["entries"]]}
        target_id = draft["revision"]["id"]
        try:
            draft = api.request("PUT", PATH + "/versions/" + target_id, update)["version"]
        except Exception:
            recovered = read(api, item)
            if (recovered["version"]["id"] == target_id and recovered.get("base_active") == base
                    and canonical(recovered["source"]) == wanted):
                return recovered
            draft = recovered.get("draft")
            if (recovered["version"] != base or not _healthy(draft, base)
                    or draft["revision"]["id"] != target_id or canonical(draft["source"]) != wanted):
                raise
        verified_version(draft)
        if not _healthy(draft, base) or draft["revision"]["id"] != target_id or canonical(draft["source"]) != wanted:
            raise ValueError("Черновик отличается от запрошенного оригинала")
    target_id = draft["revision"]["id"]
    try:
        api.request("POST", PATH + "/versions/" + target_id + "/publish",
                    {"expected_active": base, "expected_draft": draft["revision"], "confirm": True})
    except Exception:
        confirmed = read(api, item)
        if (confirmed.get("unsupported") or confirmed["version"]["id"] != target_id
                or confirmed.get("base_active") != base or canonical(confirmed["source"]) != wanted):
            raise
        return confirmed
    confirmed = read(api, item)
    if (confirmed.get("unsupported") or confirmed["version"]["id"] != target_id
            or confirmed.get("base_active") != base or canonical(confirmed["source"]) != wanted):
        raise ValueError("Публикация цен не подтверждена точным серверным оригиналом")
    return confirmed
