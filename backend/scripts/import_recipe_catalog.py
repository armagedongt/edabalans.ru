"""Import a raw or curated food catalog into the shared recipe calculator.

SQLite and JSONL inputs are read-only.  Curated imports can deactivate only rows
explicitly covered by their curation log; personal and unrelated shared products
are never hidden.  A single original row can be restored by source URL.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Iterable

REQUIRED = {"protein", "fat", "carbohydrate", "kcal"}


def normalize_name(value: object) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > 255:
        raise ValueError("invalid name")
    return name


def normalized_key(value: str) -> str:
    return normalize_name(value).casefold()


def sqlite_rows(path: Path) -> tuple[list[dict[str, object]], int]:
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


def jsonl_rows(
    path: Path, *, only_source_url: str | None = None
) -> tuple[list[dict[str, object]], int]:
    complete: list[dict[str, object]] = []
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                source_url = str(payload["source_url"])
                if only_source_url is not None and source_url != only_source_url:
                    continue
                name = normalize_name(payload["name"])
                values = {field: float(payload[field]) for field in REQUIRED}
                if any(value < 0 for value in values.values()):
                    raise ValueError("negative nutrient")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                skipped += 1
                continue
            complete.append({"source_url": source_url, "name": name, **values})
    return complete, skipped


def source_rows(
    path: Path, *, only_source_url: str | None = None
) -> tuple[list[dict[str, object]], int]:
    if path.suffix.casefold() in {".sqlite", ".sqlite3", ".db"}:
        rows, skipped = sqlite_rows(path)
        if only_source_url is not None:
            rows = [row for row in rows if row["source_url"] == only_source_url]
        return rows, skipped
    return jsonl_rows(path, only_source_url=only_source_url)


def managed_source_urls(path: Path) -> set[str]:
    urls: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            source_url = payload.get("source_url")
            if source_url:
                urls.add(str(source_url))
    return urls


def _catalog_result(rows: Iterable[dict[str, object]], skipped: int) -> dict[str, int]:
    materialized = list(rows)
    return {
        "source_rows": len(materialized) + skipped,
        "eligible": len(materialized),
        "skipped": skipped,
        "created": 0,
        "updated": 0,
        "deactivated": 0,
    }


def import_catalog(
    path: Path,
    *,
    dry_run: bool,
    deactivate_missing: bool = False,
    curation_log: Path | None = None,
    only_source_url: str | None = None,
) -> dict[str, int]:
    if deactivate_missing and curation_log is None:
        raise ValueError("curation_log is required with deactivate_missing")
    if only_source_url is not None and deactivate_missing:
        raise ValueError("single-row restore cannot deactivate other products")
    rows, skipped = source_rows(path, only_source_url=only_source_url)
    if only_source_url is not None and not rows:
        raise ValueError(f"source_url not found: {only_source_url}")
    result = _catalog_result(rows, skipped)
    if dry_run:
        return result
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.recipe_models import NutritionProduct

    active_urls = {str(row["source_url"]) for row in rows}
    managed_urls = managed_source_urls(curation_log) if curation_log else set()
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
        if deactivate_missing:
            shared = db.scalars(
                select(NutritionProduct).where(
                    NutritionProduct.owner_user_id.is_(None),
                    NutritionProduct.source_url.is_not(None),
                )
            ).all()
            for product in shared:
                source_url = str(product.source_url)
                is_managed = source_url in managed_urls or source_url.startswith(
                    "curated://recipe-catalog/"
                )
                if is_managed and source_url not in active_urls and product.is_active:
                    product.is_active = False
                    result["deactivated"] += 1
        db.commit()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--catalog", type=Path)
    source.add_argument("--sqlite", type=Path, help="legacy alias for a raw SQLite catalog")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--deactivate-missing", action="store_true")
    parser.add_argument("--curation-log", type=Path)
    parser.add_argument("--only-source-url")
    args = parser.parse_args()
    print(
        import_catalog(
            args.catalog or args.sqlite,
            dry_run=args.dry_run,
            deactivate_missing=args.deactivate_missing,
            curation_log=args.curation_log,
            only_source_url=args.only_source_url,
        )
    )


if __name__ == "__main__":
    main()
