from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.account_auth_routes import require_native_user
from app.app_service import AppAccessError, require_user_resource
from app.database import get_db
from app.models import MasterclassEvent, User
from app.recipe_models import NutritionProduct, RecipeBook, RecipeIngredient
from app.recipe_service import MAX_WEIGHT, assert_recipe_owner, catalog_search, integer, normalize_name, normalized_key, product_payload, product_values, quantity, recipe_payload, validate_ingredients
from app.recipe_originals import original_records, original_record, original_source

router = APIRouter()
TUTORIAL_EVENT = "recipes_tutorial_completed"


def _tutorial_slides() -> list[dict[str, str]]:
    text = (Path(__file__).parent / "static/apps/recipes-help.md").read_text(encoding="utf-8")
    return [{"title": section.split("\n", 1)[0], "body": section.split("\n", 1)[1].strip()} for section in text.split("\n## ")[1:]]


def _error(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)


def _user(request: Request, db: Session):
    return require_user_resource(db, require_native_user(request, db), "recipes")


async def _body(request: Request) -> dict[str, Any]:
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError("Ожидается объект с данными")
    return body


@router.get("/api/apps/recipes")
def recipes_home(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        user = _user(request, db)
        recipes = db.scalars(select(RecipeBook).where(RecipeBook.owner_user_id == user.id, RecipeBook.deleted_at.is_(None)).order_by(RecipeBook.updated_at.desc())).all()
        completed = db.scalar(select(MasterclassEvent.id).where(MasterclassEvent.user_id == user.id, MasterclassEvent.event_key == TUTORIAL_EVENT)) is not None
        return {"ok": True, "tutorialCompleted": completed, "help": _tutorial_slides(), "recipes": [{"id": str(recipe.id), "title": recipe.title, "version": recipe.version, "updatedAt": recipe.updated_at.isoformat()} for recipe in recipes]}
    except AppAccessError as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/api/apps/recipes/tutorial")
def recipe_tutorial_complete(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        user = _user(request, db)
        # Serialize completions from the same user's tabs before the unique event insert.
        db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        event = db.scalar(select(MasterclassEvent.id).where(MasterclassEvent.user_id == user.id, MasterclassEvent.event_key == TUTORIAL_EVENT))
        if event is None:
            db.add(MasterclassEvent(user_id=user.id, event_key=TUTORIAL_EVENT, event_type=TUTORIAL_EVENT, placement="recipes", details={}))
        db.commit()
        return JSONResponse({"ok": True, "completed": True})
    except AppAccessError as exc:
        return _error(exc)


@router.get("/api/apps/recipes/catalog")
def recipes_catalog(request: Request, q: str = Query(min_length=1, max_length=255), db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        user = _user(request, db)
        return {"ok": True, "items": catalog_search(db, user.id, q)}
    except (AppAccessError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/apps/recipes/originals")
def originals_list(request: Request, db: Session = Depends(get_db)) -> dict:
    try:
        _user(request, db)
        return {"ok": True, "originals": [{"id": card["id"], "title": card["title"]} for card in original_records(db)]}
    except AppAccessError as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/apps/recipes/originals/{key}")
def original_get(key: str, request: Request, db: Session = Depends(get_db)) -> dict:
    try:
        _user(request, db)
        card = original_record(db, key)
        if card is None:
            raise HTTPException(404, "Оригинальный рецепт недоступен")
        return {"ok": True, "recipe": {"original": True, "title": card["title"], "yield": card["yield"], "portion": card["portion"], "notes": "Подробный рецепт: https://edabalans.ru/lk?open=recipes:" + card["step_id"], "ingredients": [{"id": original_source(card, index)["id"], "source": original_source(card, index), "weight": int(row[1])} for index, row in enumerate(card["rows"])]}}
    except AppAccessError as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/apps/recipes/products")
def recipes_personal_products(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        user = _user(request, db)
        products = db.scalars(
            select(NutritionProduct)
            .where(
                NutritionProduct.owner_user_id == user.id,
                NutritionProduct.is_active.is_(True),
            )
            .order_by(NutritionProduct.name)
        ).all()
        return {"ok": True, "products": [product_payload(product) for product in products]}
    except AppAccessError as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/apps/recipes/{recipe_id}")
def recipe_get(recipe_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return {"ok": True, "recipe": recipe_payload(db, assert_recipe_owner(db, recipe_id, _user(request, db).id))}
    except AppAccessError as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/api/apps/recipes/products")
async def product_create(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        body = await _body(request); user = _user(request, db)
        name = normalize_name(body.get("name")); key = normalized_key(name)
        exists = db.scalar(select(NutritionProduct.id).where(NutritionProduct.owner_user_id == user.id, NutritionProduct.name_normalized == key, NutritionProduct.is_active.is_(True)))
        if exists: raise ValueError("Такой личный продукт уже есть")
        product = NutritionProduct(owner_user_id=user.id, name=name, name_normalized=key, **product_values(body))
        db.add(product); db.commit(); db.refresh(product)
        return JSONResponse({"ok": True, "product": product_payload(product)})
    except (AppAccessError, ValueError) as exc:
        db.rollback(); return _error(exc)


@router.delete("/api/apps/recipes/products/{product_id}")
def product_hide(product_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        user = _user(request, db)
        product = db.scalar(select(NutritionProduct).where(NutritionProduct.id == product_id, NutritionProduct.owner_user_id == user.id, NutritionProduct.is_active.is_(True)))
        if product is None: raise HTTPException(status_code=404, detail="Продукт не найден")
        product.is_active = False; db.commit()
        return JSONResponse({"ok": True})
    except AppAccessError as exc: return _error(exc)


@router.put("/api/apps/recipes/products/{product_id}")
async def product_update(product_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        body = await _body(request); user = _user(request, db)
        product = db.scalar(select(NutritionProduct).where(NutritionProduct.id == product_id, NutritionProduct.owner_user_id == user.id, NutritionProduct.is_active.is_(True)))
        if product is None: raise HTTPException(status_code=404, detail="Продукт не найден")
        name = normalize_name(body.get("name")); values = product_values(body)
        product.name = name; product.name_normalized = normalized_key(name)
        for key, value in values.items():
            setattr(product, key, value)
        db.commit(); return JSONResponse({"ok": True, "product": product_payload(product)})
    except (AppAccessError, ValueError) as exc:
        db.rollback(); return _error(exc)


def _save_recipe(db: Session, user_id: uuid.UUID, body: dict[str, Any], recipe: RecipeBook | None = None) -> RecipeBook:
    if "shrinkage" in body:
        raise ValueError("Старый формат с усушкой больше не поддерживается. Обновите приложение и укажите выход и порцию.")
    title = normalize_name(body.get("title"))
    yield_g = quantity(body.get("yield"), "Вес готового блюда")
    portion_g = quantity(body.get("portion"), "Вес порции")
    if portion_g > yield_g:
        raise ValueError("Вес порции не должен превышать готовый выход")
    if recipe is not None:
        recipe = assert_recipe_owner(db, recipe.id, user_id, lock=True)
        if integer(body.get("version"), "Версия", positive=True) != recipe.version:
            raise HTTPException(status_code=409, detail="Рецепт изменён в другой вкладке. Обновите страницу.")
    notes = body.get("notes", recipe.notes if recipe else "")
    if not isinstance(notes, str) or len(notes) > 10000:
        raise ValueError("Примечания: не более 10 000 символов")
    prepared = validate_ingredients(db, user_id, recipe.id if recipe else None, body.get("ingredients"))
    if recipe is None:
        recipe = RecipeBook(owner_user_id=user_id, title=title, notes=notes, yield_g=yield_g, portion_g=portion_g); db.add(recipe); db.flush()
    else:
        recipe.title = title; recipe.notes = notes; recipe.yield_g = yield_g; recipe.portion_g = portion_g; recipe.version += 1
        db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).delete(synchronize_session=False)
    for data in prepared: db.add(RecipeIngredient(recipe_id=recipe.id, **data))
    db.flush()
    return recipe


@router.post("/api/apps/recipes")
async def recipe_create(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        body = await _body(request); recipe = _save_recipe(db, _user(request, db).id, body)
        payload = recipe_payload(db, recipe)
        db.commit(); return JSONResponse({"ok": True, "recipe": payload})
    except (AppAccessError, ValueError) as exc: db.rollback(); return _error(exc)


@router.put("/api/apps/recipes/{recipe_id}")
async def recipe_update(recipe_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        body = await _body(request); user = _user(request, db); recipe = _save_recipe(db, user.id, body, assert_recipe_owner(db, recipe_id, user.id))
        payload = recipe_payload(db, recipe)
        db.commit(); return JSONResponse({"ok": True, "recipe": payload})
    except (AppAccessError, ValueError) as exc: db.rollback(); return _error(exc)


@router.delete("/api/apps/recipes/{recipe_id}")
def recipe_delete(recipe_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        user = _user(request, db); recipe = assert_recipe_owner(db, recipe_id, user.id)
        used = db.scalar(select(RecipeIngredient.id).join(RecipeBook, RecipeBook.id == RecipeIngredient.recipe_id).where(RecipeIngredient.nested_recipe_id == recipe.id, RecipeBook.deleted_at.is_(None)).limit(1))
        if used: raise ValueError("Это блюдо используется в другом рецепте. Сначала замените его там.")
        recipe.deleted_at = recipe.updated_at; db.commit(); return JSONResponse({"ok": True})
    except (AppAccessError, ValueError) as exc: return _error(exc)
