from __future__ import annotations

import re
import uuid
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from typing import Any

from fastapi import HTTPException
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.recipe_models import NutritionProduct, RecipeBook, RecipeIngredient

INTEGER_RE = re.compile(r"^[0-9]+$")
NUTRITION_RE = re.compile(r"^[0-9]+(?:[.,][0-9]{1,3})?$")
QUANTITY_RE = re.compile(r"^[0-9]+(?:[.,][0-9]{1,28})?$")
NUTRIENTS = ("protein", "fat", "carbohydrate", "calories")
MAX_WEIGHT = 99999
CURATED_CATALOG_PREFIX = "curated://recipe-catalog/"


def normalize_name(value: Any) -> str:
    name = " ".join(value.split()) if isinstance(value, str) else ""
    if not name or len(name) > 255:
        raise ValueError("Введите название до 255 символов")
    return name


def normalized_key(value: str) -> str:
    return normalize_name(value).casefold()


def integer(value: Any, field: str, *, positive: bool = False, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}: допустимы только целые цифры")
    raw = str(value).strip()
    if not INTEGER_RE.fullmatch(raw):
        raise ValueError(f"{field}: допустимы только целые цифры")
    result = int(raw)
    if positive and result <= 0:
        raise ValueError(f"{field}: значение должно быть больше нуля")
    if maximum is not None and result > maximum:
        raise ValueError(f"{field}: максимум {maximum}")
    return result


def quantity(value: Any, field: str) -> Decimal:
    raw = str(value).strip()
    if isinstance(value, bool) or len(raw) > 35 or not QUANTITY_RE.fullmatch(raw):
        raise ValueError(f"{field}: введите вес цифрами")
    number = Decimal(raw.replace(",", "."))
    if not 1 <= number <= MAX_WEIGHT:
        raise ValueError(f"{field}: от 1 до 99 999 г")
    return number


def quantity_payload(value: Decimal) -> int | str:
    return int(value) if value == int(value) else format(value, "f").rstrip("0")


def nutrition_decimal(value: Any, field: str, maximum: int) -> Decimal:
    raw = str(value).strip()
    if isinstance(value, bool) or not NUTRITION_RE.fullmatch(raw):
        raise ValueError(f"{field}: введите неотрицательное число, не более трёх знаков после запятой")
    result = Decimal(raw.replace(",", "."))
    if result > maximum:
        raise ValueError(f"{field}: максимум {maximum}")
    return result


def product_values(body: dict[str, Any]) -> dict[str, Decimal]:
    return {
        "protein_g": nutrition_decimal(body.get("protein"), "Белки", 100),
        "fat_g": nutrition_decimal(body.get("fat"), "Жиры", 100),
        "carbohydrate_g": nutrition_decimal(body.get("carbohydrate"), "Углеводы", 100),
        "calories_kcal": nutrition_decimal(body.get("calories"), "Калории", 1000),
    }


def decimal_payload(value: Decimal, places: str) -> str:
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def _product_milli(product: NutritionProduct) -> dict[str, int]:
    return {key: int(value * 1000) for key, value in zip(NUTRIENTS, (
        product.protein_g, product.fat_g, product.carbohydrate_g, product.calories_kcal,
    ))}


def _exact_payload(values: dict[str, Fraction | int], unit: str) -> dict[str, Any]:
    return {"unit": unit, **{
        key: {"numerator": str(Fraction(values[key]).numerator),
              "denominator": str(Fraction(values[key]).denominator)}
        for key in NUTRIENTS
    }}


def product_payload(product: NutritionProduct) -> dict[str, Any]:
    return {
        "id": str(product.id), "kind": "product", "name": product.name,
        "protein": decimal_payload(product.protein_g, "0.001"),
        "fat": decimal_payload(product.fat_g, "0.001"),
        "carbohydrate": decimal_payload(product.carbohydrate_g, "0.001"),
        "calories": decimal_payload(product.calories_kcal, "0.001"),
        "isPersonal": product.owner_user_id is not None,
        "exact": _exact_payload(_product_milli(product), "per100_milli"),
    }


def _ingredients(db: Session, recipe_id: uuid.UUID) -> list[RecipeIngredient]:
    return list(db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id).order_by(RecipeIngredient.sort_order, RecipeIngredient.created_at)))


def _recipe_totals(
    db: Session, recipe: RecipeBook, seen: set[uuid.UUID] | None = None,
    cache: dict[uuid.UUID, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    seen = set() if seen is None else seen
    cache = {} if cache is None else cache
    if recipe.id in seen:
        raise ValueError("Нельзя использовать рецепт внутри самого себя")
    if recipe.id in cache:
        return cache[recipe.id]
    seen.add(recipe.id)
    total: dict[str, Any] = {key: Fraction(0) for key in NUTRIENTS}
    total.update(weight=0, yield_g=recipe.yield_g, rows=[])
    try:
        for item in _ingredients(db, recipe.id):
            if item.nutrition_snapshot is not None:
                source = deepcopy(item.nutrition_snapshot)
                source.update(id=str(item.id), kind="snapshot", isPersonal=True)
                coefficients = {key: Fraction(int(source["exact"][key]["numerator"]), int(source["exact"][key]["denominator"])) for key in NUTRIENTS}
            elif item.nutrition_product_id:
                product = db.get(NutritionProduct, item.nutrition_product_id)
                if product is None or product.owner_user_id not in (None, recipe.owner_user_id):
                    raise ValueError("Продукт в рецепте недоступен")
                coefficients = _product_milli(product)
                source = product_payload(product)
            else:
                nested = db.get(RecipeBook, item.nested_recipe_id)
                if nested is None or nested.deleted_at is not None or nested.owner_user_id != recipe.owner_user_id:
                    raise ValueError("Вложенный рецепт больше недоступен")
                nested_total = _recipe_totals(db, nested, seen, cache)
                coefficients = {key: nested_total[key] / Fraction(nested.yield_g) for key in NUTRIENTS}
                source = _recipe_source(nested, nested_total)
            # Values are in 1e-5 units; a product's per100_milli times grams is exact.
            values = {key: Fraction(coefficients[key]) * item.weight_g for key in NUTRIENTS}
            total["weight"] += item.weight_g
            for key in NUTRIENTS:
                total[key] += values[key]
            total["rows"].append({"item": item, "source": source, "values": values})
    finally:
        seen.remove(recipe.id)
    cache[recipe.id] = total
    return total


def _values_payload(values: dict[str, Any], factor: Fraction = Fraction(1)) -> dict[str, str]:
    result = {}
    for key in NUTRIENTS:
        value = Fraction(values[key]) * factor
        divisor = 100000 if key == "calories" else 10000
        denominator = value.denominator * divisor
        rounded = (2 * value.numerator + denominator) // (2 * denominator)
        result[key] = str(rounded) if key == "calories" else f"{rounded // 10}.{rounded % 10}"
    return result


def _recipe_source(recipe: RecipeBook, totals: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(recipe.id), "kind": "recipe", "name": recipe.title,
        **_values_payload(totals, Fraction(100) / Fraction(recipe.yield_g)), "isPersonal": True,
        "exact": _exact_payload({key: totals[key] / Fraction(recipe.yield_g) for key in NUTRIENTS}, "per100_milli"),
    }


def contribution_ranks(values: list[dict[str, Fraction]]) -> list[dict[str, int | None]]:
    ranks = {key: {v: i + 1 for i, v in enumerate(
        sorted({row[key] for row in values if row[key] > 0}, reverse=True)[:3]
    )} for key in NUTRIENTS}
    return [{key: ranks[key].get(row[key]) for key in NUTRIENTS} for row in values]


def recipe_payload(db: Session, recipe: RecipeBook) -> dict[str, Any]:
    totals = _recipe_totals(db, recipe)
    if totals["weight"] <= 0 or recipe.yield_g <= 0:
        raise ValueError("Вес готового блюда должен быть больше нуля")
    rows = []
    ranks = contribution_ranks([row["values"] for row in totals["rows"]])
    for row, rank in zip(totals["rows"], ranks):
        item = row["item"]
        rows.append({
            "id": str(item.id), "source": row["source"], "weight": item.weight_g,
            "per100": _values_payload(row["values"], Fraction(100, item.weight_g)),
            "total": _values_payload(row["values"]),
            "exact": _exact_payload(row["values"], "1e-5"), "ranks": rank,
        })
    return {
        "id": str(recipe.id), "title": recipe.title, "notes": recipe.notes, "yield": quantity_payload(recipe.yield_g),
        "portion": quantity_payload(recipe.portion_g), "version": recipe.version, "ingredients": rows,
        "totals": {
            "weight": str(totals["weight"]), "yield": str(quantity_payload(recipe.yield_g)), "portion": str(quantity_payload(recipe.portion_g)),
            "all": _values_payload(totals),
            "per100": _values_payload(totals, Fraction(100) / Fraction(recipe.yield_g)),
            "perPortion": _values_payload(totals, Fraction(recipe.portion_g) / Fraction(recipe.yield_g)),
            "exact": _exact_payload(totals, "1e-5"),
        },
    }


def assert_recipe_owner(db: Session, recipe_id: uuid.UUID, owner_id: uuid.UUID, *, lock: bool = False) -> RecipeBook:
    statement = select(RecipeBook).where(RecipeBook.id == recipe_id, RecipeBook.owner_user_id == owner_id, RecipeBook.deleted_at.is_(None))
    if lock:
        # Refresh any previously loaded identity after the PostgreSQL lock is acquired.
        statement = statement.with_for_update().execution_options(populate_existing=True)
    recipe = db.scalar(statement)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Рецепт не найден")
    return recipe


def catalog_search(db: Session, owner_id: uuid.UUID, query: str) -> list[dict[str, Any]]:
    needle = normalized_key(query)
    products = db.scalars(
        select(NutritionProduct)
        .where(
            NutritionProduct.is_active.is_(True),
            (NutritionProduct.owner_user_id.is_(None))
            | (NutritionProduct.owner_user_id == owner_id),
            NutritionProduct.name_normalized.contains(needle),
        )
        .order_by(
            case((NutritionProduct.name_normalized.startswith(needle), 0), else_=1),
            case((NutritionProduct.owner_user_id.is_not(None), 0), else_=1),
            case(
                (
                    NutritionProduct.source_url.startswith(CURATED_CATALOG_PREFIX),
                    0,
                ),
                else_=1,
            ),
            NutritionProduct.name,
        )
        .limit(12)
    ).all()
    recipes = db.scalars(select(RecipeBook).where(RecipeBook.owner_user_id == owner_id, RecipeBook.deleted_at.is_(None), RecipeBook.title.ilike(f"%{normalize_name(query)}%")).order_by(case((RecipeBook.title.ilike(f"{normalize_name(query)}%"), 0), else_=1), RecipeBook.updated_at.desc()).limit(8)).all()
    result = [product_payload(product) for product in products]
    for recipe in recipes:
        total = _recipe_totals(db, recipe)
        result.append(_recipe_source(recipe, total))
    return result


def validate_ingredients(db: Session, owner_id: uuid.UUID, recipe_id: uuid.UUID | None, values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not values:
        raise ValueError("Добавьте хотя бы один продукт")
    if len(values) > 100:
        raise ValueError("В рецепте может быть не более 100 продуктов")
    prepared: list[dict[str, Any]] = []
    existing_rows = _ingredients(db, recipe_id) if recipe_id else []
    existing_products = {item.nutrition_product_id for item in existing_rows}
    existing_snapshots = {str(item.id): item.nutrition_snapshot for item in existing_rows if item.nutrition_snapshot is not None}
    originals = None
    for index, row in enumerate(values):
        if not isinstance(row, dict):
            raise ValueError("Некорректная строка продукта")
        kind, source_id = row.get("kind"), row.get("sourceId")
        weight = integer(row.get("weight"), "Вес", positive=True, maximum=MAX_WEIGHT)
        if kind in ("original", "snapshot"):
            if kind == "original":
                from app.recipe_originals import original_records, resolve_original_source
                if originals is None:
                    originals = {card["id"]: card for card in original_records(db)}
                snapshot = resolve_original_source(db, source_id, cards=originals)
            else:
                snapshot = existing_snapshots.get(str(source_id))
                if snapshot is None:
                    try:
                        snapshot_id = uuid.UUID(str(source_id))
                    except (ValueError, TypeError) as exc:
                        raise ValueError("Ингредиент сохранённого рецепта недоступен") from exc
                    owned = db.scalar(select(RecipeIngredient).join(RecipeBook, RecipeBook.id == RecipeIngredient.recipe_id).where(RecipeIngredient.id == snapshot_id, RecipeBook.owner_user_id == owner_id, RecipeIngredient.nutrition_snapshot.is_not(None)))
                    if owned is None:
                        raise ValueError("Ингредиент сохранённого рецепта недоступен")
                    snapshot = owned.nutrition_snapshot
            prepared.append({"nutrition_product_id": None, "nested_recipe_id": None, "nutrition_snapshot": deepcopy(snapshot), "weight_g": weight, "sort_order": index})
            continue
        try:
            parsed_id = uuid.UUID(str(source_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Выберите продукт из подсказки") from exc
        if kind == "product":
            product = db.scalar(select(NutritionProduct).where(NutritionProduct.id == parsed_id, (NutritionProduct.owner_user_id.is_(None)) | (NutritionProduct.owner_user_id == owner_id)))
            if product is None or (not product.is_active and product.id not in existing_products):
                raise ValueError("Продукт недоступен")
            prepared.append({"nutrition_product_id": product.id, "nested_recipe_id": None, "weight_g": weight, "sort_order": index})
        elif kind == "recipe":
            nested = assert_recipe_owner(db, parsed_id, owner_id)
            if recipe_id and nested.id == recipe_id:
                raise ValueError("Нельзя вложить рецепт в самого себя")
            if recipe_id and recipe_id in _descendants(db, nested.id):
                raise ValueError("Нельзя создать цикл между рецептами")
            prepared.append({"nutrition_product_id": None, "nested_recipe_id": nested.id, "weight_g": weight, "sort_order": index})
        else:
            raise ValueError("Выберите продукт из подсказки")
    if sum(row["weight_g"] for row in prepared) > MAX_WEIGHT:
        raise ValueError("Суммарный вес: максимум 99999 г")
    return prepared


def _descendants(db: Session, recipe_id: uuid.UUID, seen: set[uuid.UUID] | None = None) -> set[uuid.UUID]:
    seen = set() if seen is None else seen
    if recipe_id in seen:
        return seen
    seen.add(recipe_id)
    children = db.scalars(select(RecipeIngredient.nested_recipe_id).where(RecipeIngredient.recipe_id == recipe_id, RecipeIngredient.nested_recipe_id.is_not(None))).all()
    for child in children:
        _descendants(db, child, seen)
    return seen
