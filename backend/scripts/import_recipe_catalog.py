"""Load only complete Calorizator food cards into the shared recipe catalog.

The SQLite file is read-only. A card is eligible only when every required nutrient
has a numeric value; incomplete cards are counted and skipped rather than repaired.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

REQUIRED = {"protein", "fat", "carbohydrate", "kcal"}


def normalize_name(value: object) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > 255:
        raise ValueError("invalid name")
    return name


def normalized_key(value: str) -> str:
    return normalize_name(value).casefold()


def source_rows(path: Path) -> tuple[list[dict[str, object]], int]:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    nutrients: dict[str, dict[str, float]] = defaultdict(dict)
    for row in connection.execute("SELECT source_url, field_code, value_number FROM product_nutrients"):
        if row["field_code"] in REQUIRED and row["value_number"] is not None:
            nutrients[row["source_url"]][row["field_code"]] = float(row["value_number"])
    complete: list[dict[str, object]] = []
    skipped = 0
    for product in connection.execute("SELECT source_url, name FROM products"):
        values = nutrients.get(product["source_url"], {})
        if REQUIRED - values.keys() or not product["name"]:
            skipped += 1
            continue
        try:
            name = normalize_name(product["name"])
        except ValueError:
            skipped += 1
            continue
        complete.append({"source_url": product["source_url"], "name": name, **values})
    return complete, skipped


def import_catalog(path: Path, *, dry_run: bool) -> dict[str, int]:
    rows, skipped = source_rows(path)
    result = {"source_rows": len(rows) + skipped, "eligible": len(rows), "skipped": skipped, "created": 0, "updated": 0}
    if dry_run:
        return result
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.recipe_models import NutritionProduct
    with SessionLocal() as db:
        for row in rows:
            product = db.scalar(select(NutritionProduct).where(NutritionProduct.source_url == row["source_url"]))
            created = product is None
            if product is None:
                product = NutritionProduct(source_url=str(row["source_url"]), owner_user_id=None, name=str(row["name"]), name_normalized=normalized_key(str(row["name"])), protein_g=Decimal(str(row["protein"])), fat_g=Decimal(str(row["fat"])), carbohydrate_g=Decimal(str(row["carbohydrate"])), calories_kcal=Decimal(str(row["kcal"])), is_active=True)
                db.add(product)
            else:
                product.name = str(row["name"]); product.name_normalized = normalized_key(str(row["name"])); product.protein_g = Decimal(str(row["protein"])); product.fat_g = Decimal(str(row["fat"])); product.carbohydrate_g = Decimal(str(row["carbohydrate"])); product.calories_kcal = Decimal(str(row["kcal"])); product.is_active = True
            result["created" if created else "updated"] += 1
        db.commit()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(import_catalog(args.sqlite, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
