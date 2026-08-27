import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Resource, User, UserAccess, UserEmail  # noqa: E402
from app.recipe_models import NutritionProduct  # noqa: E402


def make_client():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), factory


def grant_user(db, email: str) -> User:
    user = User(display_name=email, status="active")
    resource = db.scalar(select(Resource).where(Resource.code == "recipes"))
    if resource is None:
        resource = Resource(code="recipes", name="Калькулятор рецептов", status="active")
        db.add(resource)
    db.add(user); db.flush()
    db.add(UserEmail(user_id=user.id, email_original=email, email_normalized=email, source="test"))
    db.add(UserAccess(user_id=user.id, resource_id=resource.id, source="test", granted_at=datetime.now(timezone.utc)))
    return user


def test_recipe_api_keeps_personal_products_private_and_calculates_yield():
    client, factory = make_client()
    with factory() as db:
        first = grant_user(db, "first@example.test")
        second = grant_user(db, "second@example.test")
        db.add(NutritionProduct(name="Сливки", name_normalized="сливки", protein_g=3, fat_g=20, carbohydrate_g=4, calories_kcal=210, is_active=True))
        db.add(NutritionProduct(owner_user_id=second.id, name="Секрет", name_normalized="секрет", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=20, is_active=True))
        db.commit()

    catalog = client.get("/api/apps/recipes/catalog", params={"email": "first@example.test", "q": "сли"}).json()
    assert catalog["ok"] is True
    cream = catalog["items"][0]
    assert client.get("/api/apps/recipes/catalog", params={"email": "first@example.test", "q": "секрет"}).json()["items"] == []

    created = client.post("/api/apps/recipes", json={"email": "first@example.test", "title": "Сливочный соус", "shrinkage": "20", "ingredients": [{"kind": "product", "sourceId": cream["id"], "weight": "200"}]}).json()
    assert created["ok"] is True
    assert created["recipe"]["totals"]["weight"] == "200"
    assert created["recipe"]["totals"]["yield"] == "180"
    assert created["recipe"]["totals"]["all"]["calories"] == "420"


def test_recipe_rejects_decimal_numeric_input_and_excessive_shrinkage():
    client, factory = make_client()
    with factory() as db:
        grant_user(db, "person@example.test")
        product = NutritionProduct(name="Молоко", name_normalized="молоко", protein_g=3, fat_g=2, carbohydrate_g=5, calories_kcal=50, is_active=True)
        db.add(product); db.commit(); product_id = str(product.id)

    bad_weight = client.post("/api/apps/recipes", json={"email":"person@example.test","title":"Тест","shrinkage":"0","ingredients":[{"kind":"product","sourceId":product_id,"weight":"10.5"}]})
    assert bad_weight.status_code == 400
    bad_loss = client.post("/api/apps/recipes", json={"email":"person@example.test","title":"Тест","shrinkage":"100","ingredients":[{"kind":"product","sourceId":product_id,"weight":"100"}]})
    assert bad_loss.status_code == 400


def test_personal_product_hides_from_search_but_keeps_saved_recipe_and_recipe_is_owner_scoped():
    client, factory = make_client()
    with factory() as db:
        grant_user(db, "owner@example.test")
        grant_user(db, "other@example.test")
    product = client.post("/api/apps/recipes/products", json={"email":"owner@example.test","name":"Мой творог","protein":"16","fat":"5","carbohydrate":"3","calories":"120"}).json()["product"]
    created = client.post("/api/apps/recipes", json={"email":"owner@example.test","title":"Завтрак","shrinkage":"0","ingredients":[{"kind":"product","sourceId":product["id"],"weight":"150"}]}).json()["recipe"]
    assert client.delete(f"/api/apps/recipes/products/{product['id']}", params={"email":"owner@example.test"}).status_code == 200
    assert client.get("/api/apps/recipes/catalog", params={"email":"owner@example.test", "q":"творог"}).json()["items"] == []
    assert client.get(f"/api/apps/recipes/{created['id']}", params={"email":"owner@example.test"}).json()["recipe"]["ingredients"][0]["source"]["name"] == "Мой творог"
    assert client.get(f"/api/apps/recipes/{created['id']}", params={"email":"other@example.test"}).status_code == 404
    assert client.delete(f"/api/apps/recipes/{created['id']}", params={"email":"other@example.test"}).status_code == 404


def test_nested_recipe_cannot_be_deleted_or_cycled():
    client, factory = make_client()
    with factory() as db:
        grant_user(db, "nested@example.test")
        product = NutritionProduct(name="Курица", name_normalized="курица", protein_g=20, fat_g=5, carbohydrate_g=0, calories_kcal=125, is_active=True)
        db.add(product); db.commit(); product_id = str(product.id)
    base = client.post("/api/apps/recipes", json={"email":"nested@example.test","title":"Основа","shrinkage":"0","ingredients":[{"kind":"product","sourceId":product_id,"weight":"100"}]}).json()["recipe"]
    parent = client.post("/api/apps/recipes", json={"email":"nested@example.test","title":"Суп","shrinkage":"0","ingredients":[{"kind":"recipe","sourceId":base["id"],"weight":"100"}]}).json()["recipe"]
    assert client.delete(f"/api/apps/recipes/{base['id']}", params={"email":"nested@example.test"}).status_code == 400
    cycle = client.put(f"/api/apps/recipes/{base['id']}", json={"email":"nested@example.test","title":"Основа","version":base["version"],"shrinkage":"0","ingredients":[{"kind":"recipe","sourceId":parent["id"],"weight":"100"}]})
    assert cycle.status_code == 400
