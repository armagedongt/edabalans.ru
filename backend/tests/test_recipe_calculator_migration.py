"""Migration and concurrent writes on an isolated, opt-in local PostgreSQL."""

import importlib.util
import os
import uuid
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import Base
from app.models import User
from app.recipe_models import NutritionProduct, RecipeBook, RecipeIngredient
from app.recipe_routes import _save_recipe


@pytest.fixture
def postgres_engine():
    url = os.getenv("RECIPE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set RECIPE_TEST_POSTGRES_URL to an isolated local PostgreSQL for migration/concurrency evidence")
    parsed = sa.engine.make_url(url)
    if parsed.get_backend_name() != "postgresql" or parsed.host not in ("127.0.0.1", "localhost", "::1"):
        pytest.fail("Recipe tests only write to an explicitly configured local PostgreSQL")
    schema = "recipe_test_" + uuid.uuid4().hex
    admin = sa.create_engine(url)
    with admin.begin() as connection:
        connection.execute(sa.schema.CreateSchema(schema))
    engine = sa.create_engine(url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=10000"})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(sa.schema.DropSchema(schema, cascade=True))
        admin.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def migration_engine(request):
    if request.param == "postgresql":
        return request.getfixturevalue("postgres_engine")
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    request.addfinalizer(engine.dispose)
    return engine


def legacy_tables(engine, *, full_source=False):
    metadata = sa.MetaData()
    books = sa.Table(
        "recipe_books", metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("shrinkage_g", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("shrinkage_g >= 0", name="ck_recipe_book_shrinkage_nonnegative"),
    )
    ingredients = sa.Table(
        "recipe_ingredients", metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("recipe_id", sa.Uuid(), sa.ForeignKey("recipe_books.id"), nullable=False),
        sa.Column("nested_recipe_id", sa.Uuid(), sa.ForeignKey("recipe_books.id")),
        *([sa.Column("nutrition_product_id", sa.Uuid()), sa.CheckConstraint("(nutrition_product_id IS NOT NULL AND nested_recipe_id IS NULL) OR (nutrition_product_id IS NULL AND nested_recipe_id IS NOT NULL)", name="ck_recipe_ingredient_single_source")] if full_source else []),
        sa.Column("weight_g", sa.Integer(), nullable=False),
        sa.CheckConstraint("weight_g > 0", name="ck_recipe_ingredient_weight_positive"),
    )
    metadata.create_all(engine)
    return books, ingredients


def migrate(connection, filename="20261003_0050_recipe_yield_portion.py"):
    path = Path(__file__).parents[1] / "migrations/versions" / filename
    spec = importlib.util.spec_from_file_location("recipe_mass_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


def test_notes_snapshot_migration_preserves_legacy_and_enforces_one_source(migration_engine):
    engine = migration_engine
    books, ingredients = legacy_tables(engine, full_source=True)
    recipe_id, product_id, row_id = (uuid.uuid4() for _ in range(3))
    with engine.begin() as connection:
        connection.execute(books.insert(), {"id": recipe_id, "shrinkage_g": 25})
        connection.execute(ingredients.insert(), {"id": row_id, "recipe_id": recipe_id, "nutrition_product_id": product_id, "weight_g": 100})
        migrate(connection)
        migrate(connection, "20261003_0051_recipe_notes.py")
    metadata = sa.MetaData()
    new_books = sa.Table("recipe_books", metadata, autoload_with=engine)
    new_rows = sa.Table("recipe_ingredients", metadata, autoload_with=engine)
    if engine.dialect.name == "sqlite":
        for table, columns in ((new_books, ("id",)), (new_rows, ("id", "recipe_id", "nutrition_product_id", "nested_recipe_id"))):
            for name in columns:
                table.c[name].type = sa.Uuid()
    with engine.connect() as connection:
        saved = connection.execute(sa.select(new_books)).mappings().one()
        assert saved["notes"] == "" and saved["yield_g"] == saved["portion_g"] == 75
        old_row = connection.execute(sa.select(new_rows)).mappings().one()
        assert uuid.UUID(str(old_row["nutrition_product_id"])) == product_id and old_row["nutrition_snapshot"] is None
    snapshot = {"exact": {"unit": "per100_milli", "protein": {"numerator": "100000", "denominator": "3"}}}
    with engine.begin() as connection:
        connection.execute(new_rows.insert(), {"id": uuid.uuid4(), "recipe_id": recipe_id, "weight_g": 6, "nutrition_snapshot": snapshot})
    for values in ({}, {"nutrition_product_id": product_id, "nutrition_snapshot": snapshot}, {"nested_recipe_id": recipe_id, "nutrition_snapshot": snapshot}):
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as connection:
                connection.execute(new_rows.insert(), {"id": uuid.uuid4(), "recipe_id": recipe_id, "weight_g": 1, **values})
    if engine.dialect.name == "postgresql":
        periodic = Decimal("320.6666666666666666666666667")
        with engine.begin() as connection:
            connection.execute(new_books.update().values(yield_g=Decimal("962"), portion_g=periodic, notes="Порядок\nhttps://example.test/recipe"))
        with engine.connect() as connection:
            saved = connection.execute(sa.select(new_books)).mappings().one()
            assert saved["portion_g"] == periodic
            assert saved["notes"] == "Порядок\nhttps://example.test/recipe"
            assert connection.scalar(sa.select(new_rows.c.nutrition_snapshot).where(new_rows.c.nutrition_snapshot.is_not(None))) == snapshot


def test_migration_backfills_active_deleted_and_nested_recipes(migration_engine):
    engine = migration_engine
    books, ingredients = legacy_tables(engine)
    base, parent, deleted = (uuid.uuid4() for _ in range(3))
    with engine.begin() as connection:
        connection.execute(books.insert(), [
            {"id": base, "shrinkage_g": 20, "deleted_at": None},
            {"id": parent, "shrinkage_g": 0, "deleted_at": None},
            {"id": deleted, "shrinkage_g": 5, "deleted_at": datetime.now(timezone.utc)},
        ])
        connection.execute(ingredients.insert(), [
            {"id": uuid.uuid4(), "recipe_id": base, "nested_recipe_id": None, "weight_g": 100},
            {"id": uuid.uuid4(), "recipe_id": base, "nested_recipe_id": None, "weight_g": 200},
            {"id": uuid.uuid4(), "recipe_id": parent, "nested_recipe_id": base, "weight_g": 70},
            {"id": uuid.uuid4(), "recipe_id": deleted, "nested_recipe_id": None, "weight_g": 30},
        ])
    with engine.begin() as connection:
        migrate(connection)
    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT yield_g, portion_g FROM recipe_books ORDER BY yield_g")).all()
        assert rows == [(25, 25), (70, 70), (280, 280)]
        assert connection.scalar(sa.text("SELECT count(*) FROM recipe_ingredients")) == 4
        assert connection.scalar(sa.text("SELECT count(*) FROM recipe_books WHERE deleted_at IS NOT NULL")) == 1
    assert "shrinkage_g" not in {column["name"] for column in sa.inspect(engine).get_columns("recipe_books")}


def test_migration_empty_database_and_new_constraints(migration_engine):
    engine = migration_engine
    legacy_tables(engine)
    with engine.begin() as connection:
        migrate(connection)
    for yield_g, portion in ((0, 1), (100000, 1), (100, 0), (100, 101)):
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as connection:
                connection.execute(sa.text("INSERT INTO recipe_books (id, yield_g, portion_g) VALUES (:id,:y,:p)"),
                                   {"id": uuid.uuid4().hex, "y": yield_g, "p": portion})
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO recipe_books (id, yield_g, portion_g) VALUES (:id,99999,99999)"),
                           {"id": uuid.uuid4().hex})
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT count(*) FROM recipe_books")) == 1


@pytest.mark.parametrize("weights,shrinkage", [([], 0), ([100], 100), ([100000], 0), ([60000, 60000], 0), ([1] * 101, 0)])
def test_migration_refuses_invalid_legacy_without_changes(migration_engine, weights, shrinkage):
    engine = migration_engine
    books, ingredients = legacy_tables(engine)
    recipe_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(books.insert(), {"id": recipe_id, "shrinkage_g": shrinkage,
                                           "deleted_at": datetime.now(timezone.utc)})
        if weights:
            connection.execute(ingredients.insert(), [
                {"id": uuid.uuid4(), "recipe_id": recipe_id, "weight_g": weight} for weight in weights
            ])
    with pytest.raises(RuntimeError, match="1 invalid legacy recipes"):
        with engine.begin() as connection:
            migrate(connection)
    assert "yield_g" not in {column["name"] for column in sa.inspect(engine).get_columns("recipe_books")}
    with engine.connect() as connection:
        assert connection.scalar(sa.select(books.c.shrinkage_g)) == shrinkage
        assert connection.scalar(sa.select(sa.func.count()).select_from(ingredients)) == len(weights)


def test_postgres_competing_same_version_writes_preserve_winning_composition(postgres_engine):
    engine = postgres_engine
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        owner = User(display_name="Synthetic recipe test", status="active")
        product = NutritionProduct(name="Protein", name_normalized="protein", protein_g=1, fat_g=0, carbohydrate_g=0, calories_kcal=4)
        db.add_all([owner, product]); db.flush()
        recipe = RecipeBook(owner_user_id=owner.id, title="Original", yield_g=100, portion_g=50)
        db.add(recipe); db.flush()
        db.add(RecipeIngredient(recipe_id=recipe.id, nutrition_product_id=product.id, weight_g=100, sort_order=0))
        db.commit()
        owner_id, recipe_id, product_id = owner.id, recipe.id, product.id
    barrier = Barrier(2)

    def update(weight):
        with Session(engine, expire_on_commit=False) as db:
            stale = db.get(RecipeBook, recipe_id)
            assert stale.version == 1
            barrier.wait(timeout=5)
            body = {"title": f"Winner {weight}", "yield": weight, "portion": weight, "version": 1,
                    "ingredients": [{"kind": "product", "sourceId": str(product_id), "weight": weight}]}
            try:
                saved = _save_recipe(db, owner_id, body, stale)
                db.commit()
                return (200, saved.title, weight)
            except HTTPException as exc:
                db.rollback()
                return (exc.status_code, None, None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update, weight) for weight in (200, 300)]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(status for status, _, _ in results) == [200, 409]
    winner = next(result for result in results if result[0] == 200)
    with Session(engine) as db:
        saved = db.get(RecipeBook, recipe_id)
        assert (saved.version, saved.title, saved.yield_g, saved.portion_g) == (2, winner[1], winner[2], winner[2])
        rows = list(db.scalars(sa.select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id)))
        assert len(rows) == 1 and rows[0].weight_g == winner[2]
