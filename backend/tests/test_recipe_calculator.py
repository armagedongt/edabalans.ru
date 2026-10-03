import os
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("APP_AUTH_SECRET", "test-client-session-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.account_security import password_hash  # noqa: E402
from app.main import app  # noqa: E402
import app.main as main_module  # noqa: E402
from app.models import AccountCredential, MasterclassEvent, Resource, User, UserAccess, UserCoursePolicy, UserEmail, UserLegalAcceptance  # noqa: E402
from app.legal_service import LEGAL_DOCUMENTS  # noqa: E402
from app.recipe_models import NutritionProduct, RecipeBook  # noqa: E402
from app.recipe_service import NUTRIENTS, contribution_ranks, nutrition_decimal  # noqa: E402
from app.product_catalog_service import PRODUCT_CONNECTIONS  # noqa: E402


def make_client():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(database_url="sqlite+pysqlite:///:memory:", app_auth_secret="test-client-session-secret")
    main_module.SessionLocal = factory
    return TestClient(app, base_url="https://edabalans.ru"), factory


def grant_user(db, email: str) -> User:
    user = User(display_name=email, status="active")
    resource = db.scalar(select(Resource).where(Resource.code == "recipes"))
    if resource is None:
        resource = Resource(code="recipes", name="Калькулятор рецептов", status="active")
        db.add(resource)
    db.add(user); db.flush()
    db.add(UserEmail(user_id=user.id, email_original=email, email_normalized=email, source="test"))
    db.add(AccountCredential(user_id=user.id, password_hash=password_hash("Test-Password-9", "test-client-session-secret"), password_version=1, issued_via="test"))
    db.add(UserAccess(user_id=user.id, resource_id=resource.id, source="test", granted_at=datetime.now(timezone.utc)))
    db.add_all([
        UserLegalAcceptance(
            user_id=user.id,
            document_code=document["code"],
            document_version=document["version"],
            source="test",
        )
        for document in LEGAL_DOCUMENTS
    ])
    return user


def sign_in(client: TestClient, email: str) -> None:
    response = client.post("/api/account-auth/login", json={"email": email, "password": "Test-Password-9"})
    assert response.status_code == 200, response.text


def test_recipe_api_keeps_personal_products_private_and_calculates_yield():
    client, factory = make_client()
    with factory() as db:
        first = grant_user(db, "first@example.test")
        second = grant_user(db, "second@example.test")
        db.add(NutritionProduct(name="Сливки", name_normalized="сливки", protein_g=3, fat_g=20, carbohydrate_g=4, calories_kcal=210, is_active=True))
        db.add(NutritionProduct(owner_user_id=second.id, name="Секрет", name_normalized="секрет", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=20, is_active=True))
        db.commit()
    sign_in(client, "first@example.test")

    catalog = client.get("/api/apps/recipes/catalog", params={"email": "first@example.test", "q": "сли"}).json()
    assert catalog["ok"] is True
    cream = catalog["items"][0]
    assert client.get("/api/apps/recipes/catalog", params={"email": "first@example.test", "q": "секрет"}).json()["items"] == []

    created = client.post("/api/apps/recipes", json={"email": "first@example.test", "title": "Сливочный соус", "yield": "180", "portion": "90", "ingredients": [{"kind": "product", "sourceId": cream["id"], "weight": "200"}]}).json()
    assert created["ok"] is True
    assert created["recipe"]["totals"]["weight"] == "200"
    assert created["recipe"]["totals"]["yield"] == "180"
    assert created["recipe"]["totals"]["all"]["calories"] == "420"


def test_recipe_calculator_does_not_depend_on_course_start_gate():
    client, factory = make_client()
    with factory() as db:
        user = grant_user(db, "gated@example.test")
        course = Resource(code="ACCESS_RECIPES", name="Система рецептов", status="active")
        db.add(course)
        db.flush()
        db.add(UserCoursePolicy(user_id=user.id, resource_id=course.id, start_mode="blocked", source="test"))
        db.commit()
    sign_in(client, "gated@example.test")

    assert client.get("/api/apps/recipes").json()["ok"] is True


def test_recipe_rejects_decimal_weight_and_zero_yield():
    client, factory = make_client()
    with factory() as db:
        grant_user(db, "person@example.test")
        product = NutritionProduct(name="Молоко", name_normalized="молоко", protein_g=3, fat_g=2, carbohydrate_g=5, calories_kcal=50, is_active=True)
        db.add(product); db.commit(); product_id = str(product.id)
    sign_in(client, "person@example.test")

    bad_weight = client.post("/api/apps/recipes", json={"email":"person@example.test","title":"Тест","yield":"100","portion":"50","ingredients":[{"kind":"product","sourceId":product_id,"weight":"10.5"}]})
    assert bad_weight.status_code == 400
    bad_yield = client.post("/api/apps/recipes", json={"email":"person@example.test","title":"Тест","yield":"0","portion":"1","ingredients":[{"kind":"product","sourceId":product_id,"weight":"100"}]})
    assert bad_yield.status_code == 400


def test_catalog_search_prioritizes_names_starting_with_query():
    client, factory = make_client()
    with factory() as db:
        user = grant_user(db, "search@example.test")
        db.add_all([
            NutritionProduct(owner_user_id=user.id, name="Молоко моё", name_normalized="молоко моё", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=10, is_active=True),
            NutritionProduct(name="Блины с молоком", name_normalized="блины с молоком", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=10, is_active=True),
            NutritionProduct(source_url="https://example.test/branded-milk", name="Молоко брендовое 1%", name_normalized="молоко брендовое 1%", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=10, is_active=True),
            NutritionProduct(source_url="curated://recipe-catalog/v1/milk", name="Молоко 2% *", name_normalized="молоко 2% *", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=10, is_active=True),
            NutritionProduct(name="Молоко 1%", name_normalized="молоко 1%", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=10, is_active=True),
            NutritionProduct(name="Кофе с молоком", name_normalized="кофе с молоком", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=10, is_active=True),
        ])
        db.commit()
    sign_in(client, "search@example.test")

    items = client.get("/api/apps/recipes/catalog", params={"email": "search@example.test", "q": "молоко"}).json()["items"]
    assert [item["name"] for item in items] == [
        "Молоко моё",
        "Молоко 2% *",
        "Молоко 1%",
        "Молоко брендовое 1%",
        "Блины с молоком",
        "Кофе с молоком",
    ]


def test_personal_product_hides_from_search_but_keeps_saved_recipe_and_recipe_is_owner_scoped():
    client, factory = make_client()
    with factory() as db:
        grant_user(db, "owner@example.test")
        grant_user(db, "other@example.test")
        db.commit()
    sign_in(client, "owner@example.test")
    product_response = client.post("/api/apps/recipes/products", json={"email":"owner@example.test","name":"Мой творог","protein":"16","fat":"5","carbohydrate":"3","calories":"120"})
    assert product_response.status_code == 200, product_response.text
    product = product_response.json()["product"]
    personal = client.get("/api/apps/recipes/products", params={"email": "owner@example.test"}).json()
    assert personal["ok"] is True
    assert [item["id"] for item in personal["products"]] == [product["id"]]
    created = client.post("/api/apps/recipes", json={"email":"owner@example.test","title":"Завтрак","yield":"150","portion":"50","ingredients":[{"kind":"product","sourceId":product["id"],"weight":"150"}]}).json()["recipe"]
    assert client.delete(f"/api/apps/recipes/products/{product['id']}", params={"email":"owner@example.test"}).status_code == 200
    assert client.get("/api/apps/recipes/catalog", params={"email":"owner@example.test", "q":"творог"}).json()["items"] == []
    assert client.get(f"/api/apps/recipes/{created['id']}", params={"email":"owner@example.test"}).json()["recipe"]["ingredients"][0]["source"]["name"] == "Мой творог"
    sign_in(client, "other@example.test")
    assert client.get(f"/api/apps/recipes/{created['id']}").status_code == 404
    assert client.delete(f"/api/apps/recipes/{created['id']}").status_code == 404


def test_recipe_product_retains_base_readiness():
    connection = PRODUCT_CONNECTIONS["recipes"]
    # Учебная карточка открывает самостоятельный курс, а не калькулятор.
    assert {key: connection[key] for key in ("resource", "app", "ready")} == {
        "resource": "ACCESS_RECIPES",
        "app": "recipes-course",
        "ready": True,
    }


def test_nested_recipe_cannot_be_deleted_or_cycled():
    client, factory = make_client()
    with factory() as db:
        grant_user(db, "nested@example.test")
        product = NutritionProduct(name="Курица", name_normalized="курица", protein_g=20, fat_g=5, carbohydrate_g=0, calories_kcal=125, is_active=True)
        db.add(product); db.commit(); product_id = str(product.id)
    sign_in(client, "nested@example.test")
    base = client.post("/api/apps/recipes", json={"email":"nested@example.test","title":"Основа","yield":"100","portion":"50","ingredients":[{"kind":"product","sourceId":product_id,"weight":"100"}]}).json()["recipe"]
    parent = client.post("/api/apps/recipes", json={"email":"nested@example.test","title":"Суп","yield":"100","portion":"50","ingredients":[{"kind":"recipe","sourceId":base["id"],"weight":"100"}]}).json()["recipe"]
    assert client.delete(f"/api/apps/recipes/{base['id']}", params={"email":"nested@example.test"}).status_code == 400
    cycle = client.put(f"/api/apps/recipes/{base['id']}", json={"email":"nested@example.test","title":"Основа","version":base["version"],"yield":"100","portion":"50","ingredients":[{"kind":"recipe","sourceId":parent["id"],"weight":"100"}]})
    assert cycle.status_code == 400


@pytest.fixture
def recipe_client():
    original_factory = main_module.SessionLocal
    client, factory = make_client()
    with factory() as db:
        grant_user(db, "calculator@example.test")
        db.commit()
    sign_in(client, "calculator@example.test")
    try:
        yield client, factory
    finally:
        client.close()
        app.dependency_overrides.clear()
        main_module.SessionLocal = original_factory
        factory.kw["bind"].dispose()


def add_product(client, name="Продукт", **values):
    body = {"name": name, "protein": "1", "fat": "0", "carbohydrate": "0", "calories": "4", **values}
    response = client.post("/api/apps/recipes/products", json=body)
    assert response.status_code == 200, response.text
    return response.json()["product"]


def recipe_body(source, *, weight=100, yield_g=100, portion=50, kind="product", title="Блюдо"):
    return {"title": title, "yield": yield_g, "portion": portion,
            "ingredients": [{"kind": kind, "sourceId": source["id"], "weight": weight}]}


def exact_value(payload, key):
    value = payload[key]
    return Fraction(int(value["numerator"]), int(value["denominator"]))


@pytest.mark.parametrize("value", [True, None, "-1", "1.0001", "NaN", "Infinity", "1e2", "", "1,2.3", "100.001"])
def test_nutrition_parser_rejects_invalid_or_excess_precision(value):
    with pytest.raises(ValueError):
        nutrition_decimal(value, "Белки", 100)


@pytest.mark.parametrize("raw,expected", [("0", "0"), (" 12,345 ", "12.345"), ("100.000", "100.000"), (0.125, "0.125")])
def test_nutrition_parser_accepts_exact_thousandths(raw, expected):
    assert nutrition_decimal(raw, "Белки", 100) == Decimal(expected)


def test_contribution_ranks_use_distinct_exact_values_before_display_rounding():
    numbers = [Fraction(1), Fraction(1), Fraction(99999, 100000), Fraction(1, 2), Fraction(0), Fraction(1, 4)]
    fats = [3, 0, 2, 5, 1, 5]
    carbs = [0, 5, 2, 2, 1, 4]
    calories = [2, 0, 7, 3, 7, 1]
    rows = [dict(protein=value, fat=Fraction(fats[i]), carbohydrate=Fraction(carbs[i]), calories=Fraction(calories[i]))
            for i, value in enumerate(numbers)]
    ranked = contribution_ranks(rows)
    assert [row["protein"] for row in ranked] == [1, 1, 2, 3, None, None]
    assert [row["fat"] for row in ranked] == [2, None, 3, 1, None, 1]
    assert [row["carbohydrate"] for row in ranked] == [None, 1, 3, 3, None, 2]
    assert [row["calories"] for row in ranked] == [3, None, 1, 2, 1, None]
    assert contribution_ranks([{key: Fraction(0) for key in NUTRIENTS}]) == [{key: None for key in NUTRIENTS}]


def test_decimal_product_create_update_and_failed_update_leave_valid_values(recipe_client):
    client, _ = recipe_client
    product = add_product(client, protein="12,345", fat="100.000", carbohydrate="0.001", calories="1000.000")
    assert product["protein"] == "12.345"
    assert exact_value(product["exact"], "protein") == 12345
    assert product["exact"]["unit"] == "per100_milli"
    changed = client.put(f"/api/apps/recipes/products/{product['id']}", json={
        "name": "Обновлённый", "protein": "1.001", "fat": "0", "carbohydrate": "0", "calories": "4,004",
    })
    assert changed.status_code == 200
    assert changed.json()["product"]["protein"] == "1.001"
    invalid = client.put(f"/api/apps/recipes/products/{product['id']}", json={
        "name": "Не должен записаться", "protein": "1", "fat": "0", "carbohydrate": "0", "calories": "1000.001",
    })
    assert invalid.status_code == 400
    stored = client.get("/api/apps/recipes/products").json()["products"][0]
    assert stored["name"] == "Обновлённый" and stored["protein"] == "1.001"


@pytest.mark.parametrize("field,value", [("protein", "100.001"), ("fat", -1), ("carbohydrate", "0.0001"), ("calories", "1000.001")])
def test_product_api_bounds_are_checked_before_database_write(recipe_client, field, value):
    client, factory = recipe_client
    response = client.post("/api/apps/recipes/products", json={
        "name": "Недопустимый", "protein": "0", "fat": "0", "carbohydrate": "0", "calories": "0", field: value,
    })
    assert response.status_code == 400
    with factory() as db:
        assert db.scalar(select(NutritionProduct.id)) is None


def test_direct_yield_portion_persistence_crud_and_version_conflict(recipe_client):
    client, factory = recipe_client
    product = add_product(client, protein="12.345", fat="2.345", carbohydrate="4.567", calories="100")
    body = recipe_body(product, weight=250, yield_g=500, portion=125)
    # Client calculations are not an input to authoritative totals.
    body["totals"] = {"calories": "999999"}
    created_response = client.post("/api/apps/recipes", json=body)
    assert created_response.status_code == 200, created_response.text
    recipe = created_response.json()["recipe"]
    assert recipe["yield"] == 500 and recipe["portion"] == 125
    assert "shrinkage" not in recipe and "raw" not in recipe["totals"]
    assert recipe["totals"]["all"]["calories"] == "250"
    assert recipe["totals"]["per100"]["calories"] == "50"
    assert recipe["totals"]["perPortion"]["calories"] == "63"
    assert exact_value(recipe["ingredients"][0]["exact"], "protein") == 12345 * 250
    assert recipe["ingredients"][0]["per100"] == {"protein": "12.3", "fat": "2.3", "carbohydrate": "4.6", "calories": "100"}
    assert recipe["ingredients"][0]["total"] == {"protein": "30.9", "fat": "5.9", "carbohydrate": "11.4", "calories": "250"}
    reopened = client.get(f"/api/apps/recipes/{recipe['id']}").json()["recipe"]
    assert reopened == recipe
    update_body = {**body, "yield": 600, "portion": 100, "version": recipe["version"]}
    updated = client.put(f"/api/apps/recipes/{recipe['id']}", json=update_body).json()["recipe"]
    assert updated["version"] == 2
    assert updated["totals"]["all"] == recipe["totals"]["all"]
    assert client.put(f"/api/apps/recipes/{recipe['id']}", json={**update_body, "title": "Устаревший"}).status_code == 409
    assert client.get(f"/api/apps/recipes/{recipe['id']}").json()["recipe"] == updated
    assert client.delete(f"/api/apps/recipes/{recipe['id']}").status_code == 200
    assert client.get(f"/api/apps/recipes/{recipe['id']}").status_code == 404
    assert client.get("/api/apps/recipes").json()["recipes"] == []
    with factory() as db:
        assert db.scalar(select(RecipeBook)).deleted_at is not None


def test_nested_periodic_coefficient_retains_exact_equality_and_shared_rank(recipe_client):
    client, _ = recipe_client
    product = add_product(client)
    base = client.post("/api/apps/recipes", json=recipe_body(product, yield_g=3, portion=3, title="Основа")).json()["recipe"]
    found = client.get("/api/apps/recipes/catalog", params={"q": "Основа"}).json()["items"][0]
    assert exact_value(found["exact"], "protein") == Fraction(100000, 3)
    body = recipe_body(base, weight=3, kind="recipe", yield_g=103, portion=103)
    body["ingredients"].append({"kind": "product", "sourceId": product["id"], "weight": 100})
    parent = client.post("/api/apps/recipes", json=body).json()["recipe"]
    assert [exact_value(r["exact"], "protein") for r in parent["ingredients"]] == [100000, 100000]
    assert [r["total"]["protein"] for r in parent["ingredients"]] == ["1.0", "1.0"]
    assert [r["ranks"]["protein"] for r in parent["ingredients"]] == [1, 1]
    assert parent["totals"]["all"]["protein"] == "2.0"
    assert all(r["ranks"]["fat"] is None for r in parent["ingredients"])
    assert client.get(f"/api/apps/recipes/{parent['id']}").json()["recipe"] == parent
    grand_body = recipe_body(parent, weight=103, kind="recipe", yield_g=206, portion=103)
    grand_body["ingredients"].append({"kind": "recipe", "sourceId": parent["id"], "weight": 103})
    grand = client.post("/api/apps/recipes", json=grand_body).json()["recipe"]
    assert grand["totals"]["all"]["protein"] == "4.0"


def test_caesar_exact_totals_half_up_and_portion(recipe_client):
    client, _ = recipe_client
    data = [
        ("Айсберг", 250, "0.9", "0.1", "1.8", "14"),
        ("Грудка", 250, "18", "5", "0", "117"),
        ("Черри", 200, "0.8", "0.1", "2.8", "15"),
        ("Огурец", 100, "2.8", "0", "1.3", "16"),
        ("Перец", 50, "2.8", "0", "1.3", "16"),
        ("Шпинат", 50, "2.9", "0.3", "2", "22"),
        ("Сухарики", 50, "10.5", "15.7", "66", "445"),
        ("Соус", 50, "0", "20", "10.7", "224"),
        ("Сыр", 50, "18.5", "14", "0", "240"),
    ]
    ingredients = []
    for name, weight, protein, fat, carbohydrate, calories in data:
        product = add_product(client, name, protein=protein, fat=fat, carbohydrate=carbohydrate, calories=calories)
        ingredients.append({"kind": "product", "sourceId": product["id"], "weight": weight})
    response = client.post("/api/apps/recipes", json={"title": "Цезарь", "yield": 1050, "portion": 525, "ingredients": ingredients})
    assert response.status_code == 200, response.text
    totals = response.json()["recipe"]["totals"]
    assert totals["weight"] == "1050"
    assert [exact_value(totals["exact"], k) / 100000 for k in NUTRIENTS] == [Fraction(69), Fraction(759, 20), Fraction(257, 5), Fraction(847)]
    assert totals["all"] == dict(protein="69.0", fat="38.0", carbohydrate="51.4", calories="847")
    assert totals["per100"] == dict(protein="6.6", fat="3.6", carbohydrate="4.9", calories="81")
    assert totals["perPortion"] == dict(protein="34.5", fat="19.0", carbohydrate="25.7", calories="424")


def test_hidden_source_grandfathered_only_within_original_recipe(recipe_client):
    client, _ = recipe_client
    product = add_product(client)
    body = recipe_body(product)
    recipe = client.post("/api/apps/recipes", json=body).json()["recipe"]
    assert client.delete(f"/api/apps/recipes/products/{product['id']}").status_code == 200
    assert client.post("/api/apps/recipes", json=body).status_code == 400
    update_body = {**body, "title": "Изменённое блюдо", "version": recipe["version"]}
    updated = client.put(f"/api/apps/recipes/{recipe['id']}", json=update_body)
    assert updated.status_code == 200, updated.text
    assert updated.json()["recipe"]["totals"]["all"]["protein"] == "1.0"
    active = add_product(client, "Другой")
    other = client.post("/api/apps/recipes", json=recipe_body(active)).json()["recipe"]
    assert client.put(f"/api/apps/recipes/{other['id']}", json={**body, "version": other["version"]}).status_code == 400


@pytest.mark.parametrize("field,value", [("yield", 0), ("yield", 100000), ("portion", 0), ("portion", 101), ("portion", 100000), ("yield", True), ("portion", "1e2")])
def test_recipe_weight_parameters_reject_out_of_range_without_write(recipe_client, field, value):
    client, factory = recipe_client
    body = recipe_body(add_product(client))
    body[field] = value
    assert client.post("/api/apps/recipes", json=body).status_code == 400
    with factory() as db:
        assert db.scalar(select(RecipeBook.id)) is None


def test_recipe_ingredient_limits_legacy_contract_and_invalid_body(recipe_client):
    client, _ = recipe_client
    product = add_product(client)
    body = recipe_body(product, weight=99999, yield_g=99999, portion=99999)
    assert client.post("/api/apps/recipes", json=body).status_code == 200
    for weight in (0, -1, 100000, True, "1.001"):
        assert client.post("/api/apps/recipes", json=recipe_body(product, weight=weight)).status_code == 400
    for ingredients in ([], [{}], [{"kind": "product", "sourceId": "", "weight": 1}], body["ingredients"] * 2,
                        recipe_body(product, weight=1)["ingredients"] * 101):
        assert client.post("/api/apps/recipes", json={**body, "ingredients": ingredients}).status_code == 400
    assert client.post("/api/apps/recipes", json={**body, "title": ""}).status_code == 400
    assert client.post("/api/apps/recipes", json={"title": "Старый", "shrinkage": 0, "ingredients": body["ingredients"]}).status_code == 400
    for malformed in (None, [], "text"):
        assert client.post("/api/apps/recipes", json=malformed).status_code == 400


def test_foreign_product_recipe_write_and_revoked_resource_are_denied(recipe_client):
    client, factory = recipe_client
    product = add_product(client)
    recipe = client.post("/api/apps/recipes", json=recipe_body(product)).json()["recipe"]
    with factory() as db:
        other = grant_user(db, "stranger@example.test")
        db.commit()
        other_id = other.id
    spoof = {"email": "stranger@example.test"}
    assert client.get("/api/apps/recipes", params=spoof).status_code == 403
    assert client.post("/api/apps/recipes", json={**recipe_body(product), **spoof}).status_code == 403
    # The route must use the native session even without the public-host email filter.
    client.base_url = "https://localhost"
    sign_in(client, "calculator@example.test")
    assert [r["id"] for r in client.get("/api/apps/recipes", params=spoof).json()["recipes"]] == [recipe["id"]]
    assert [p["id"] for p in client.get("/api/apps/recipes/products", params=spoof).json()["products"]] == [product["id"]]
    forged = client.post("/api/apps/recipes", params=spoof, json={**recipe_body(product), **spoof})
    assert forged.status_code == 200, forged.text
    forged_id = forged.json()["recipe"]["id"]
    sign_in(client, "stranger@example.test")
    assert client.get(f"/api/apps/recipes/{forged_id}").status_code == 404
    assert client.post("/api/apps/recipes", json=recipe_body(product)).status_code == 400
    assert client.post("/api/apps/recipes", json=recipe_body(recipe, kind="recipe")).status_code == 404
    assert client.put(f"/api/apps/recipes/{recipe['id']}", json={**recipe_body(product), "version": 1}).status_code == 404
    assert client.put(f"/api/apps/recipes/products/{product['id']}", json={"name": "Чужой"}).status_code == 404
    assert client.delete(f"/api/apps/recipes/products/{product['id']}").status_code == 404
    with factory() as db:
        access = db.scalar(select(UserAccess).where(UserAccess.user_id == other_id))
        access.revoked_at = datetime.now(timezone.utc)
        db.commit()
    assert client.get("/api/apps/recipes").json()["ok"] is False


def seed_original(db, *, active=True):
    from app.course_material_service import material_source
    from app.models import ContentItem, ContentItemVersion
    from scripts.publish_recipe_originals import publish

    source = material_source(db, create=True)
    item = ContentItem(source_id=source.id, external_id="day-15-recipe-synthetic", canonical_url="https://example.test/synthetic", title="Синтетическая статья", metadata_json={"other_owner": "preserved"})
    db.add(item); db.flush()
    version = ContentItemVersion(item_id=item.id, version_no=1, content_hash="1" * 64, text_content="<p>Синтетическое описание.</p>", parser_version="test")
    db.add(version); db.flush(); item.latest_version_id = version.id; db.flush()
    card = {"id": "synthetic", "title": "Синтетический оригинал", "active": active, "yield": "75.5", "portion": "37.75", "rows": [["Тестовый ингредиент", "3", "1", "0.01", "0", "4"]]}
    bundle = {"materials": [{"step_id": item.external_id, "expected_version": 1, "source_hash": "2" * 64, "cards": [card, {"id": "inactive", "title": "Без БЖУ", "active": False}]}]}
    assert publish(db, bundle, apply=True) == {"materials": 1, "active": int(active), "inactive": 2 - int(active), "applied": True}
    assert item.metadata_json["other_owner"] == "preserved"
    return item, bundle


def test_original_copy_is_exact_private_and_independent_of_later_original_edits(recipe_client):
    client, factory = recipe_client
    with factory() as db:
        seed_original(db)
        grant_user(db, "original-stranger@example.test")
        db.commit()
    originals = client.get("/api/apps/recipes/originals").json()
    assert originals == {"ok": True, "originals": [{"id": "synthetic", "title": "Синтетический оригинал"}]}
    assert client.get("/api/apps/recipes/originals/inactive").status_code == 404
    original = client.get("/api/apps/recipes/originals/synthetic").json()["recipe"]
    source = original["ingredients"][0]["source"]
    assert exact_value(source["exact"], "protein") == Fraction(100000, 3)
    body = {key: original[key] for key in ("title", "yield", "portion", "notes")}
    body["ingredients"] = [{"kind": "original", "sourceId": source["id"], "weight": "6", "nutrition_snapshot": {"protein": "forged"}}]
    response = client.post("/api/apps/recipes", json=body)
    assert response.status_code == 200, response.text
    saved = response.json()["recipe"]
    assert saved["totals"]["all"]["protein"] == "2.0"
    assert saved["yield"] == "75.5" and saved["portion"] == "37.75"
    assert saved["notes"] == original["notes"]
    assert saved["ingredients"][0]["source"]["kind"] == "snapshot"
    assert client.get("/api/apps/recipes/originals/synthetic").json()["recipe"] == original
    with factory() as db:
        from app.course_material_service import material_item
        from scripts.publish_recipe_originals import publish
        item = material_item(db, "day-15-recipe-synthetic")
        metadata = item.metadata_json["recipe_calculator"]
        cards = metadata["cards"]
        cards[0]["rows"][0][2] = "100"
        bundle = {"materials": [{"step_id": item.external_id, "expected_version": 1, "source_hash": "3" * 64, "cards": cards}]}
        publish(db, bundle, apply=True); db.commit()
    assert client.post("/api/apps/recipes", json=body).status_code == 400, "a stale original source cannot silently use new data"
    reopened = client.get(f"/api/apps/recipes/{saved['id']}").json()["recipe"]
    assert reopened["totals"]["all"]["protein"] == "2.0"
    snapshot = reopened["ingredients"][0]["source"]
    updated_body = {**body, "notes": "Порядок\nhttps://example.test/source", "version": reopened["version"], "ingredients": [{"kind": "snapshot", "sourceId": snapshot["id"], "weight": "9"}]}
    updated = client.put(f"/api/apps/recipes/{saved['id']}", json=updated_body).json()["recipe"]
    assert updated["totals"]["all"]["protein"] == "3.0"
    assert updated["notes"] == updated_body["notes"]
    copy_ingredients = [{"kind": "snapshot", "sourceId": updated["ingredients"][0]["source"]["id"], "weight": "9"}]
    personal_copy = client.post("/api/apps/recipes", json={**body, "ingredients": copy_ingredients})
    assert personal_copy.status_code == 200
    assert personal_copy.json()["recipe"]["totals"]["all"]["protein"] == "3.0"
    sign_in(client, "original-stranger@example.test")
    assert client.get(f"/api/apps/recipes/{saved['id']}").status_code == 404
    assert client.post("/api/apps/recipes", json={**body, "ingredients": copy_ingredients}).status_code == 400
    assert client.get("/api/apps/recipes/originals").json() == originals


def test_recipe_notes_validation_and_tutorial_completion_are_native_and_idempotent(recipe_client):
    client, factory = recipe_client
    with factory() as db:
        grant_user(db, "tutorial-stranger@example.test")
        db.commit()
    home = client.get("/api/apps/recipes").json()
    assert home["tutorialCompleted"] is False and len(home["help"]) == 6
    assert "разработ" in home["help"][0]["title"].lower()
    assert client.post("/api/apps/recipes/tutorial", json={"email": "tutorial-stranger@example.test"}).status_code == 403
    for _ in range(2):
        assert client.post("/api/apps/recipes/tutorial", json={}).json() == {"ok": True, "completed": True}
    assert client.get("/api/apps/recipes").json()["tutorialCompleted"] is True
    with factory() as db:
        assert len(db.scalars(select(MasterclassEvent).where(MasterclassEvent.event_key == "recipes_tutorial_completed")).all()) == 1
    product = add_product(client)
    for notes in (None, [], 0, "x" * 10001):
        assert client.post("/api/apps/recipes", json={**recipe_body(product), "notes": notes}).status_code == 400
    saved = client.post("/api/apps/recipes", json={**recipe_body(product), "notes": "x" * 10000}).json()["recipe"]
    assert len(saved["notes"]) == 10000
    without_notes = client.put(f"/api/apps/recipes/{saved['id']}", json={**recipe_body(product), "version": saved["version"]}).json()["recipe"]
    assert without_notes["notes"] == saved["notes"]
    sign_in(client, "tutorial-stranger@example.test")
    assert client.get("/api/apps/recipes").json()["tutorialCompleted"] is False
