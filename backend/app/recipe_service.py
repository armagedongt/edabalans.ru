from __future__ import annotations

import re
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.recipe_models import NutritionProduct, RecipeBook, RecipeIngredient

INTEGER_RE = re.compile(r"^\d+$")
ZERO = Decimal("0")


def normalize_name(value: Any) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > 255:
        raise ValueError("Введите название до 255 символов")
    return name


def normalized_key(value: str) -> str:
    return normalize_name(value).casefold()


def integer(value: Any, field: str, *, positive: bool = False) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}: допустимы только целые цифры")
    raw = str(value).strip()
    if not INTEGER_RE.fullmatch(raw):
        raise ValueError(f"{field}: допустимы только целые цифры")
    result = int(raw)
    if positive and result <= 0:
        raise ValueError(f"{field}: значение должно быть больше нуля")
    return result


def decimal_payload(value: Decimal, places: str) -> str:
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def product_payload(product: NutritionProduct) -> dict[str, Any]:
    return {
        "id": str(product.id), "kind": "product", "name": product.name,
        "protein": decimal_payload(product.protein_g, "0.001"),
        "fat": decimal_payload(product.fat_g, "0.001"),
        "carbohydrate": decimal_payload(product.carbohydrate_g, "0.001"),
        "calories": decimal_payload(product.calories_kcal, "0.001"),
        "isPersonal": product.owner_user_id is not None,
    }


def _ingredients(db: Session, recipe_id: uuid.UUID) -> list[RecipeIngredient]:
    return list(db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id).order_by(RecipeIngredient.sort_order, RecipeIngredient.created_at)))


def _recipe_totals(db: Session, recipe: RecipeBook, seen: set[uuid.UUID] | None = None) -> dict[str, Decimal]:
    seen = set() if seen is None else seen
    if recipe.id in seen:
        raise ValueError("Нельзя использовать рецепт внутри самого себя")
    seen.add(recipe.id)
    total = {"weight": ZERO, "protein": ZERO, "fat": ZERO, "carbohydrate": ZERO, "calories": ZERO}
    for item in _ingredients(db, recipe.id):
        if item.nutrition_product_id:
            product = db.get(NutritionProduct, item.nutrition_product_id)
            if product is None:
                raise ValueError("Продукт в рецепте больше не существует")
            values = {"protein": product.protein_g, "fat": product.fat_g, "carbohydrate": product.carbohydrate_g, "calories": product.calories_kcal}
        else:
            nested = db.get(RecipeBook, item.nested_recipe_id)
            if nested is None or nested.deleted_at is not None:
                raise ValueError("Вложенный рецепт больше недоступен")
            nested_total = _recipe_totals(db, nested, seen)
            if nested_total["yield"] <= ZERO:
                raise ValueError("Вложенный рецепт не имеет готового выхода")
            values = {key: nested_total[key] / nested_total["yield"] * Decimal(100) for key in ("protein", "fat", "carbohydrate", "calories")}
        factor = Decimal(item.weight_g) / Decimal(100)
        total["weight"] += Decimal(item.weight_g)
        for key, value in values.items():
            total[key] += value * factor
    seen.remove(recipe.id)
    total["yield"] = total["weight"] - Decimal(recipe.shrinkage_g)
    return total


def _values_payload(values: dict[str, Decimal], basis: Decimal | None = None) -> dict[str, str]:
    if basis is None:
        values = {key: values[key] for key in ("protein", "fat", "carbohydrate", "calories")}
    else:
        if basis <= ZERO:
            values = {key: ZERO for key in ("protein", "fat", "carbohydrate", "calories")}
        else:
            values = {key: values[key] / basis * Decimal(100) for key in ("protein", "fat", "carbohydrate", "calories")}
    return {"protein": decimal_payload(values["protein"], "0.1"), "fat": decimal_payload(values["fat"], "0.1"), "carbohydrate": decimal_payload(values["carbohydrate"], "0.1"), "calories": decimal_payload(values["calories"], "1")}


def recipe_payload(db: Session, recipe: RecipeBook) -> dict[str, Any]:
    totals = _recipe_totals(db, recipe)
    if totals["weight"] <= ZERO or totals["yield"] <= ZERO:
        raise ValueError("Вес готового блюда должен быть больше нуля")
    rows = []
    for item in _ingredients(db, recipe.id):
        if item.nutrition_product_id:
            product = db.get(NutritionProduct, item.nutrition_product_id)
            assert product is not None
            source = product_payload(product)
            source_values = {"protein": product.protein_g, "fat": product.fat_g, "carbohydrate": product.carbohydrate_g, "calories": product.calories_kcal}
        else:
            nested = db.get(RecipeBook, item.nested_recipe_id)
            assert nested is not None
            nested_totals = _recipe_totals(db, nested)
            source = {"id": str(nested.id), "kind": "recipe", "name": nested.title, **_values_payload(nested_totals, nested_totals["yield"])}
            source_values = {key: nested_totals[key] / nested_totals["yield"] * Decimal(100) for key in ("protein", "fat", "carbohydrate", "calories")}
        row_values = {key: source_values[key] * Decimal(item.weight_g) / Decimal(100) for key in source_values}
        rows.append({"id": str(item.id), "source": source, "weight": item.weight_g, "per100": _values_payload(source_values), "total": _values_payload(row_values)})
    return {"id": str(recipe.id), "title": recipe.title, "shrinkage": recipe.shrinkage_g, "version": recipe.version, "ingredients": rows, "totals": {"weight": str(int(totals["weight"])), "yield": str(int(totals["yield"])), "all": _values_payload(totals), "per100": _values_payload(totals, totals["yield"]), "raw": {key: str(totals[key]) for key in totals}}}


def assert_recipe_owner(db: Session, recipe_id: uuid.UUID, owner_id: uuid.UUID) -> RecipeBook:
    recipe = db.scalar(select(RecipeBook).where(RecipeBook.id == recipe_id, RecipeBook.owner_user_id == owner_id, RecipeBook.deleted_at.is_(None)))
    if recipe is None:
        raise HTTPException(status_code=404, detail="Рецепт не найден")
    return recipe


def catalog_search(db: Session, owner_id: uuid.UUID, query: str) -> list[dict[str, Any]]:
    needle = normalized_key(query)
    products = db.scalars(select(NutritionProduct).where(NutritionProduct.is_active.is_(True), (NutritionProduct.owner_user_id.is_(None)) | (NutritionProduct.owner_user_id == owner_id), NutritionProduct.name_normalized.contains(needle)).order_by(NutritionProduct.owner_user_id.desc(), NutritionProduct.name).limit(12)).all()
    recipes = db.scalars(select(RecipeBook).where(RecipeBook.owner_user_id == owner_id, RecipeBook.deleted_at.is_(None), RecipeBook.title.ilike(f"%{normalize_name(query)}%")).order_by(RecipeBook.updated_at.desc()).limit(8)).all()
    result = [product_payload(product) for product in products]
    for recipe in recipes:
        total = _recipe_totals(db, recipe)
        if total["yield"] > ZERO:
            result.append({"id": str(recipe.id), "kind": "recipe", "name": recipe.title, **_values_payload(total, total["yield"]), "isPersonal": True})
    return result


def validate_ingredients(db: Session, owner_id: uuid.UUID, recipe_id: uuid.UUID | None, values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not values:
        raise ValueError("Добавьте хотя бы один продукт")
    if len(values) > 100:
        raise ValueError("В рецепте может быть не более 100 продуктов")
    prepared: list[dict[str, Any]] = []
    for index, row in enumerate(values):
        if not isinstance(row, dict):
            raise ValueError("Некорректная строка продукта")
        kind, source_id = row.get("kind"), row.get("sourceId")
        try:
            parsed_id = uuid.UUID(str(source_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Выберите продукт из подсказки") from exc
        weight = integer(row.get("weight"), "Вес", positive=True)
        if kind == "product":
            product = db.scalar(select(NutritionProduct).where(NutritionProduct.id == parsed_id, (NutritionProduct.owner_user_id.is_(None)) | (NutritionProduct.owner_user_id == owner_id)))
            if product is None:
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
