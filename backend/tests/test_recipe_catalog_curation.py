from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("APP_AUTH_SECRET", "test-client-session-secret")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.database as database
from app.database import Base
from app.recipe_models import NutritionProduct
from scripts.curate_recipe_catalog import Product, averaged_product, build
from scripts.import_recipe_catalog import import_catalog


NUTRIENTS = ("protein", "fat", "carbohydrate", "kcal")


def write_raw_catalog(path: Path, products: list[dict[str, object]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE products (source_url TEXT PRIMARY KEY, name TEXT, category TEXT)"
    )
    connection.execute(
        "CREATE TABLE product_nutrients "
        "(source_url TEXT, field_code TEXT, value_number REAL)"
    )
    for index, product in enumerate(products):
        source_url = f"https://example.test/{index}"
        connection.execute(
            "INSERT INTO products VALUES (?, ?, ?)",
            (source_url, product["name"], product["category"]),
        )
        connection.executemany(
            "INSERT INTO product_nutrients VALUES (?, ?, ?)",
            [(source_url, field, product[field]) for field in NUTRIENTS],
        )
    connection.commit()
    connection.close()


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_curation_collapses_only_compatible_base_products(tmp_path: Path) -> None:
    source = tmp_path / "catalog.sqlite"
    output = tmp_path / "curated"
    dairy = "Молочные продукты"
    products = [
        {"name": "Творог 5%", "category": dairy, "protein": 17, "fat": 4.8, "carbohydrate": 2, "kcal": 120},
        {"name": "Творог Простоквашино 5%", "category": dairy, "protein": 16, "fat": 5.2, "carbohydrate": 3, "kcal": 122},
        {"name": "Творог Светаево 5%", "category": dairy, "protein": 16, "fat": 5, "carbohydrate": 3, "kcal": 510},
        {"name": "Творог мягкий 5%", "category": dairy, "protein": 9, "fat": 5, "carbohydrate": 3, "kcal": 90},
        {"name": "Творог 0.5%", "category": dairy, "protein": 18, "fat": 0.5, "carbohydrate": 2, "kcal": 85},
        {"name": "Творог 0%", "category": dairy, "protein": 18, "fat": 0.2, "carbohydrate": 2, "kcal": 82},
        {"name": "Творог 1.8%", "category": dairy, "protein": 17, "fat": 1.8, "carbohydrate": 3, "kcal": 98},
        {"name": "Творог 2%", "category": dairy, "protein": 17, "fat": 2, "carbohydrate": 3, "kcal": 99},
        {"name": "Творог Чудо вишня 5%", "category": dairy, "protein": 8, "fat": 5, "carbohydrate": 14, "kcal": 135},
        {"name": "Йогурт Danone греческий с хлопьями 2%", "category": dairy, "protein": 7, "fat": 2, "carbohydrate": 11, "kcal": 91},
        {"name": "Рис белый", "category": "Крупы и каши", "protein": 7, "fat": 1, "carbohydrate": 77, "kcal": 340},
        {"name": "Рис белый отварной", "category": "Крупы и каши", "protein": 2.5, "fat": 0.3, "carbohydrate": 25, "kcal": 115},
        {"name": "Хлопья 4 злака BrandA", "category": "Крупы и каши", "protein": 11, "fat": 3, "carbohydrate": 65, "kcal": 340},
        {"name": "Хлопья 4 злака BrandB", "category": "Крупы и каши", "protein": 12, "fat": 4, "carbohydrate": 62, "kcal": 338},
        {"name": "Сыр Гауда", "category": "Сыры и творог", "protein": 25, "fat": 27, "carbohydrate": 1, "kcal": 350},
        {"name": "Сыр Российский", "category": "Сыры и творог", "protein": 24, "fat": 29, "carbohydrate": 0, "kcal": 360},
        {"name": "Салат Оливье", "category": None, "protein": 5, "fat": 12, "carbohydrate": 8, "kcal": 160},
        {"name": "Крем-суп грибной", "category": None, "protein": 3, "fat": 5, "carbohydrate": 8, "kcal": 90},
        {"name": "Суши с лососем", "category": None, "protein": 6, "fat": 3, "carbohydrate": 25, "kcal": 150},
        {"name": "Винегрет овощной готовый", "category": None, "protein": 2, "fat": 4, "carbohydrate": 9, "kcal": 75},
        {"name": "Голубцы Ремит", "category": None, "protein": 5, "fat": 9, "carbohydrate": 6, "kcal": 130},
        {"name": "Картофельное пюре Роллтон с курицей", "category": None, "protein": 10, "fat": 7, "carbohydrate": 69, "kcal": 380},
        {"name": "Курица Пятёрочка Кафе терияки с рисом и овощами", "category": None, "protein": 8, "fat": 5, "carbohydrate": 18, "kcal": 150},
        {"name": "Гречка Yelli с белыми грибами", "category": "Крупы и каши", "protein": 12, "fat": 3, "carbohydrate": 61, "kcal": 320},
        {"name": "Сливки кокосовые", "category": dairy, "protein": 1.6, "fat": 21, "carbohydrate": 4.8, "kcal": 214},
        {"name": "Сливки кокосовые сухие", "category": dairy, "protein": 0, "fat": 50, "carbohydrate": 45.9, "kcal": 526},
        {"name": "Рис нешлифованный вареный", "category": "Крупы и каши", "protein": 3, "fat": 1, "carbohydrate": 36, "kcal": 170},
        {"name": "Рис длиннозерный", "category": "Крупы и каши", "protein": 7, "fat": 1, "carbohydrate": 75, "kcal": 340},
        {"name": "Рис длиннозерный пропаренный", "category": "Крупы и каши", "protein": 7, "fat": 0.5, "carbohydrate": 78, "kcal": 350},
        {"name": "Рис Карнароли", "category": "Крупы и каши", "protein": 7, "fat": 1, "carbohydrate": 76, "kcal": 345},
        {"name": "Рис Арборио", "category": "Крупы и каши", "protein": 7, "fat": 1, "carbohydrate": 76, "kcal": 345},
    ]
    write_raw_catalog(source, products)

    summary = build(source, output)
    curated = read_jsonl(output / "curated-products.jsonl")
    log = read_jsonl(output / "curation-log.jsonl")
    by_name = {str(row["name"]): row for row in curated}

    assert summary["source_products"] == len(products)
    assert len(read_jsonl(output / "original-products.jsonl")) == len(products)
    assert len(log) == len(products)
    assert by_name["Творог 5% *"]["member_count"] == 3
    assert by_name["Творог 5% *"]["averaged_count"] == 2
    assert by_name["Творог 5% *"]["protein"] == 16.5
    assert by_name["Творог 5% *"]["fat"] == 5.0
    assert by_name["Творог 5% *"]["carbohydrate"] == 2.5
    assert by_name["Творог 5% *"]["kcal"] == 121
    assert "Творог мягкий 5% *" in by_name
    assert by_name["Творог 0% *"]["member_count"] == 2
    assert by_name["Творог 2% *"]["member_count"] == 2
    assert "Творог Чудо вишня 5%" in by_name
    assert "Йогурт Danone греческий с хлопьями 2%" not in by_name
    assert "Рис белый сухой *" in by_name
    assert "Рис белый отварной *" in by_name
    assert "Хлопья 4 злака BrandA" in by_name
    assert "Хлопья 4 злака BrandB" in by_name
    assert "Сыр Гауда *" in by_name
    assert "Сыр Российский *" in by_name
    assert "Сливки кокосовые *" in by_name
    assert "Сливки кокосовые сухие *" in by_name
    assert "Рис бурый отварной *" in by_name
    assert "Рис белый длиннозёрный сухой *" in by_name
    assert "Рис белый длиннозёрный пропаренный сухой *" in by_name
    assert "Рис карнароли сухой *" in by_name
    assert "Рис арборио сухой *" in by_name
    for ready_name in (
        "Салат Оливье",
        "Крем-суп грибной",
        "Суши с лососем",
        "Винегрет овощной готовый",
        "Голубцы Ремит",
        "Картофельное пюре Роллтон с курицей",
        "Курица Пятёрочка Кафе терияки с рисом и овощами",
        "Гречка Yelli с белыми грибами",
    ):
        assert ready_name not in by_name

    decisions = {str(row["name"]): row for row in log}
    assert decisions["Творог Светаево 5%"]["decision"] == "exclude_outlier"
    assert decisions["Йогурт Danone греческий с хлопьями 2%"]["decision"] == "exclude"
    assert decisions["Хлопья 4 злака BrandA"]["decision"] == "keep_brand"
    assert decisions["Салат Оливье"]["decision"] == "exclude"
    assert decisions["Крем-суп грибной"]["decision"] == "exclude"
    assert decisions["Суши с лососем"]["decision"] == "exclude"
    assert decisions["Винегрет овощной готовый"]["decision"] == "exclude"
    assert decisions["Голубцы Ремит"]["decision"] == "exclude"
    assert decisions["Картофельное пюре Роллтон с курицей"]["decision"] == "exclude"
    assert decisions["Курица Пятёрочка Кафе терияки с рисом и овощами"]["decision"] == "exclude"
    assert decisions["Гречка Yelli с белыми грибами"]["decision"] == "exclude"


def test_canonical_source_url_changes_when_averaged_values_change() -> None:
    base = Product("one", "Творог 5%", "Сыры и творог", 16, 5, 3, 121)
    duplicate = Product("duplicate", "Творог 5%", "Сыры и творог", 16, 5, 3, 121)
    changed = Product("two", "Творог 5%", "Сыры и творог", 17, 5, 4, 126)

    first = averaged_product("Творог 5% *", [base])
    same = averaged_product("Творог 5% *", [duplicate, base])
    reversed_same = averaged_product("Творог 5% *", [base, duplicate])
    second = averaged_product("Творог 5% *", [base, changed])

    assert first is not None
    assert same is not None
    assert reversed_same is not None
    assert second is not None
    assert first["source_url"] == same["source_url"] == reversed_same["source_url"]
    assert first["source_url"] != second["source_url"]


def test_import_deactivates_only_logged_sources_and_restores_one_row(
    tmp_path: Path, monkeypatch
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)

    raw_active = "https://example.test/brand"
    raw_hidden = "https://example.test/hidden"
    unrelated = "manual://unrelated"
    old_canonical = "curated://recipe-catalog/v1/old"
    with factory() as db:
        db.add_all(
            [
                NutritionProduct(source_url=raw_active, name="Старое имя", name_normalized="старое имя", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=10, is_active=True),
                NutritionProduct(source_url=raw_hidden, name="Скрыть", name_normalized="скрыть", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=10, is_active=True),
                NutritionProduct(source_url=unrelated, name="Ручной", name_normalized="ручной", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=10, is_active=True),
                NutritionProduct(source_url=old_canonical, name="Старый *", name_normalized="старый *", protein_g=1, fat_g=1, carbohydrate_g=1, calories_kcal=10, is_active=True),
            ]
        )
        db.commit()

    curated = tmp_path / "curated.jsonl"
    curated.write_text(
        "\n".join(
            [
                json.dumps({"source_url": "curated://recipe-catalog/v1/new", "name": "Творог 5% *", "protein": 16, "fat": 5, "carbohydrate": 3, "kcal": 121}, ensure_ascii=False),
                json.dumps({"source_url": raw_active, "name": "Особый продукт", "protein": 8, "fat": 4, "carbohydrate": 12, "kcal": 116}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    log = tmp_path / "log.jsonl"
    log.write_text(
        "\n".join(
            json.dumps({"source_url": value})
            for value in (raw_active, raw_hidden)
        )
        + "\n",
        encoding="utf-8",
    )

    result = import_catalog(
        curated,
        dry_run=False,
        deactivate_missing=True,
        curation_log=log,
    )
    assert result == {
        "source_rows": 2,
        "eligible": 2,
        "skipped": 0,
        "created": 1,
        "updated": 1,
        "deactivated": 2,
    }
    with factory() as db:
        rows = {
            row.source_url: row
            for row in db.scalars(select(NutritionProduct)).all()
        }
        assert rows[raw_active].is_active is True
        assert rows[raw_active].name == "Особый продукт"
        assert rows[raw_hidden].is_active is False
        assert rows[unrelated].is_active is True
        assert rows[old_canonical].is_active is False

    original = tmp_path / "original.jsonl"
    original.write_text(
        json.dumps(
            {
                "source_url": raw_hidden,
                "name": "Восстановленный продукт",
                "protein": 2,
                "fat": 3,
                "carbohydrate": 4,
                "kcal": 51,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    restore = import_catalog(
        original,
        dry_run=False,
        only_source_url=raw_hidden,
    )
    assert restore["updated"] == 1
    assert restore["deactivated"] == 0
    with factory() as db:
        restored = db.scalar(
            select(NutritionProduct).where(NutritionProduct.source_url == raw_hidden)
        )
        assert restored is not None
        assert restored.is_active is True
        assert restored.name == "Восстановленный продукт"
        assert float(restored.protein_g) == 2
        assert float(restored.fat_g) == 3
        assert float(restored.carbohydrate_g) == 4
        assert float(restored.calories_kcal) == 51


def test_committed_catalog_artifacts_are_complete_and_unique() -> None:
    root = Path(__file__).parents[2]
    catalog = root / "backend" / "data" / "recipe_catalog"
    original = read_jsonl(catalog / "original-products.jsonl")
    log = read_jsonl(catalog / "curation-log.jsonl")
    curated = read_jsonl(catalog / "curated-products.jsonl")
    summary = json.loads((catalog / "summary.json").read_text(encoding="utf-8"))

    original_urls = [str(row["source_url"]) for row in original]
    log_urls = [str(row["source_url"]) for row in log]
    curated_names = [" ".join(str(row["name"]).casefold().split()) for row in curated]

    assert len(original) == len(log) == summary["source_products"]
    assert summary["source_products"] == 6384
    assert summary["source_sha256"] == "f40b270fa3fcdda238999bda332e9688a62fb3cad663013615a1b9583059ca46"
    assert (
        hashlib.sha256(
            (catalog / "original-products.jsonl")
            .read_text(encoding="utf-8")
            .encode("utf-8")
        ).hexdigest()
        == "ddc84edbe8756c5c452942b9d672c9428567a36f40b037b4affed2d0c8b859ee"
    )
    assert len(curated) == summary["active_products"]
    assert len(original_urls) == len(set(original_urls))
    assert set(original_urls) == set(log_urls)
    assert len(curated_names) == len(set(curated_names))
    assert all(
        str(row["source_url"]).startswith("curated://recipe-catalog/")
        for row in curated
        if str(row["name"]).endswith(" *")
    )
