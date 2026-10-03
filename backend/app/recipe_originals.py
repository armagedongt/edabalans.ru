"""Calculator cards attached to the existing published recipe materials."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.course_material_service import latest_version, material_source
from app.models import ContentItem

METADATA_KEY = "recipe_calculator"
STEP_PREFIX = "day-15-recipe-"
NUTRIENTS = ("protein", "fat", "carbohydrate", "calories")


def validated_cards(values: Any) -> list[dict]:
    from app.recipe_service import integer, normalize_name, quantity

    if not isinstance(values, list) or not 1 <= len(values) <= 3:
        raise ValueError("Ожидаются от одной до трёх карточек статьи")
    result = []
    ids = set()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Некорректная карточка рецепта")
        key = value.get("id")
        if not isinstance(key, str) or not key or len(key) > 80 or not all(c.isascii() and (c.isalnum() or c == '-') for c in key) or key in ids:
            raise ValueError("Некорректный или повторяющийся id карточки")
        ids.add(key)
        available = value.get("active")
        if not isinstance(available, bool):
            raise ValueError("Укажите активность карточки")
        card = {"id": key, "title": normalize_name(value.get("title")), "active": available}
        if available:
            card["yield"] = str(quantity(value.get("yield"), "Выход"))
            card["portion"] = str(quantity(value.get("portion"), "Порция"))
            if Decimal(card["portion"]) > Decimal(card["yield"]):
                raise ValueError("Порция превышает выход")
            rows = value.get("rows")
            if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
                raise ValueError("Ожидаются ингредиенты карточки")
            card["rows"] = []
            for row in rows:
                if not isinstance(row, list) or len(row) != 6:
                    raise ValueError("Некорректная строка карточки")
                name = normalize_name(row[0])
                weight = integer(row[1], "Вес", positive=True, maximum=99999)
                nutrients = []
                for raw in row[2:]:
                    if not isinstance(raw, str) or len(raw) > 64 or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,28})?", raw):
                        raise ValueError("Нутриенты должны быть точными десятичными строками")
                    try:
                        number = Decimal(raw)
                    except Exception as exc:
                        raise ValueError("Некорректный нутриент") from exc
                    if not number.is_finite() or number < 0 or number > 99999000:
                        raise ValueError("Некорректный нутриент")
                    nutrients.append(str(number))
                card["rows"].append([name, str(weight), *nutrients])
            if sum(int(row[1]) for row in card["rows"]) > 99999:
                raise ValueError("Суммарный вес превышает 99 999 г")
        result.append(card)
    return result


def original_records(db: Session) -> list[dict]:
    source = material_source(db)
    if source is None or source.status != "active":
        return []
    records = []
    for item in db.scalars(select(ContentItem).where(ContentItem.source_id == source.id, ContentItem.external_id.startswith(STEP_PREFIX), ContentItem.status == "published")):
        metadata = (item.metadata_json or {}).get(METADATA_KEY, {})
        version = latest_version(db, item)
        if version is None or metadata.get("version") != version.version_no:
            continue
        for card in metadata.get("cards", []):
            if card.get("active"):
                records.append({**deepcopy(card), "step_id": item.external_id, "source_hash": metadata["source_hash"], "version": version.version_no})
    return sorted(records, key=lambda card: card["title"].casefold())


def original_record(db: Session, key: str) -> dict | None:
    return next((card for card in original_records(db) if card["id"] == key), None)


def original_source(card: dict, index: int) -> dict:
    row = card["rows"][index]
    values = {key: Fraction(Decimal(raw)) * 100000 / int(row[1]) for key, raw in zip(NUTRIENTS, row[2:])}
    return {
        "id": f"{card['id']}:{index}:{card['source_hash']}", "kind": "original", "name": row[0], "isPersonal": False,
        "exact": {"unit": "per100_milli", **{key: {"numerator": str(value.numerator), "denominator": str(value.denominator)} for key, value in values.items()}},
        "origin": {"recipe": card["id"], "step": card["step_id"], "source_hash": card["source_hash"], "version": card["version"]},
    }


def resolve_original_source(db: Session, key: str, *, cards: dict | None = None) -> dict:
    try:
        card_id, raw_index, source_hash = key.split(":")
        card = original_record(db, card_id) if cards is None else cards.get(card_id)
        index = int(raw_index)
        if card is None or card["source_hash"] != source_hash or index < 0 or index >= len(card["rows"]):
            raise ValueError
        return original_source(card, index)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Оригинальный рецепт обновлён. Откройте его заново.") from exc
