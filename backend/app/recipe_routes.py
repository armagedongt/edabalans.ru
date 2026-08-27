from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.app_service import AppAccessError, resolve_user_for_resource
from app.database import get_db
from app.recipe_models import NutritionProduct, RecipeBook, RecipeIngredient
from app.recipe_service import assert_recipe_owner, catalog_search, integer, normalize_name, normalized_key, product_payload, recipe_payload, validate_ingredients

router = APIRouter()


def _error(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)


def _user(db: Session, email: str):
    return resolve_user_for_resource(db, email, "recipes")


@router.get("/api/apps/recipes")
def recipes_home(email: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        user = _user(db, email)
        recipes = db.scalars(select(RecipeBook).where(RecipeBook.owner_user_id == user.id, RecipeBook.deleted_at.is_(None)).order_by(RecipeBook.updated_at.desc())).all()
        return {"ok": True, "recipes": [{"id": str(recipe.id), "title": recipe.title, "version": recipe.version, "updatedAt": recipe.updated_at.isoformat()} for recipe in recipes]}
    except AppAccessError as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/apps/recipes/catalog")
def recipes_catalog(email: str, q: str = Query(min_length=1, max_length=255), db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        user = _user(db, email)
        return {"ok": True, "items": catalog_search(db, user.id, q)}
    except (AppAccessError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/apps/recipes/{recipe_id}")
def recipe_get(recipe_id: uuid.UUID, email: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return {"ok": True, "recipe": recipe_payload(db, assert_recipe_owner(db, recipe_id, _user(db, email).id))}
    except AppAccessError as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/api/apps/recipes/products")
async def product_create(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        body = await request.json(); user = _user(db, body.get("email"))
        name = normalize_name(body.get("name")); key = normalized_key(name)
        exists = db.scalar(select(NutritionProduct.id).where(NutritionProduct.owner_user_id == user.id, NutritionProduct.name_normalized == key, NutritionProduct.is_active.is_(True)))
        if exists: raise ValueError("Такой личный продукт уже есть")
        product = NutritionProduct(owner_user_id=user.id, name=name, name_normalized=key, protein_g=Decimal(integer(body.get("protein"), "Белки")), fat_g=Decimal(integer(body.get("fat"), "Жиры")), carbohydrate_g=Decimal(integer(body.get("carbohydrate"), "Углеводы")), calories_kcal=Decimal(integer(body.get("calories"), "Калории")))
        db.add(product); db.commit(); db.refresh(product)
        return JSONResponse({"ok": True, "product": product_payload(product)})
    except (AppAccessError, ValueError) as exc:
        db.rollback(); return _error(exc)


@router.delete("/api/apps/recipes/products/{product_id}")
def product_hide(product_id: uuid.UUID, email: str, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        user = _user(db, email)
        product = db.scalar(select(NutritionProduct).where(NutritionProduct.id == product_id, NutritionProduct.owner_user_id == user.id, NutritionProduct.is_active.is_(True)))
        if product is None: raise HTTPException(status_code=404, detail="Продукт не найден")
        product.is_active = False; db.commit()
        return JSONResponse({"ok": True})
    except AppAccessError as exc: return _error(exc)


@router.put("/api/apps/recipes/products/{product_id}")
async def product_update(product_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        body = await request.json(); user = _user(db, body.get("email"))
        product = db.scalar(select(NutritionProduct).where(NutritionProduct.id == product_id, NutritionProduct.owner_user_id == user.id, NutritionProduct.is_active.is_(True)))
        if product is None: raise HTTPException(status_code=404, detail="Продукт не найден")
        product.name = normalize_name(body.get("name")); product.name_normalized = normalized_key(product.name)
        product.protein_g = Decimal(integer(body.get("protein"), "Белки")); product.fat_g = Decimal(integer(body.get("fat"), "Жиры")); product.carbohydrate_g = Decimal(integer(body.get("carbohydrate"), "Углеводы")); product.calories_kcal = Decimal(integer(body.get("calories"), "Калории"))
        db.commit(); return JSONResponse({"ok": True, "product": product_payload(product)})
    except (AppAccessError, ValueError) as exc:
        db.rollback(); return _error(exc)


def _save_recipe(db: Session, user_id: uuid.UUID, body: dict[str, Any], recipe: RecipeBook | None = None) -> RecipeBook:
    title = normalize_name(body.get("title")); shrinkage = integer(body.get("shrinkage", 0), "Усушка")
    if recipe is not None:
        if integer(body.get("version"), "Версия", positive=True) != recipe.version:
            raise HTTPException(status_code=409, detail="Рецепт изменён в другой вкладке. Обновите страницу.")
    prepared = validate_ingredients(db, user_id, recipe.id if recipe else None, body.get("ingredients"))
    initial_weight = sum(item["weight_g"] for item in prepared)
    if shrinkage >= initial_weight: raise ValueError("Усушка должна быть меньше общего веса")
    if recipe is None:
        recipe = RecipeBook(owner_user_id=user_id, title=title, shrinkage_g=shrinkage); db.add(recipe); db.flush()
    else:
        recipe.title = title; recipe.shrinkage_g = shrinkage; recipe.version += 1
        db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).delete(synchronize_session=False)
    for data in prepared: db.add(RecipeIngredient(recipe_id=recipe.id, **data))
    db.flush(); recipe_payload(db, recipe)
    return recipe


@router.post("/api/apps/recipes")
async def recipe_create(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        body = await request.json(); recipe = _save_recipe(db, _user(db, body.get("email")).id, body)
        db.commit(); return JSONResponse({"ok": True, "recipe": recipe_payload(db, recipe)})
    except (AppAccessError, ValueError) as exc: db.rollback(); return _error(exc)


@router.put("/api/apps/recipes/{recipe_id}")
async def recipe_update(recipe_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        body = await request.json(); user = _user(db, body.get("email")); recipe = _save_recipe(db, user.id, body, assert_recipe_owner(db, recipe_id, user.id))
        db.commit(); return JSONResponse({"ok": True, "recipe": recipe_payload(db, recipe)})
    except (AppAccessError, ValueError) as exc: db.rollback(); return _error(exc)


@router.delete("/api/apps/recipes/{recipe_id}")
def recipe_delete(recipe_id: uuid.UUID, email: str, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        user = _user(db, email); recipe = assert_recipe_owner(db, recipe_id, user.id)
        used = db.scalar(select(RecipeIngredient.id).join(RecipeBook, RecipeBook.id == RecipeIngredient.recipe_id).where(RecipeIngredient.nested_recipe_id == recipe.id, RecipeBook.deleted_at.is_(None)).limit(1))
        if used: raise ValueError("Это блюдо используется в другом рецепте. Сначала замените его там.")
        recipe.deleted_at = recipe.updated_at; db.commit(); return JSONResponse({"ok": True})
    except (AppAccessError, ValueError) as exc: return _error(exc)
