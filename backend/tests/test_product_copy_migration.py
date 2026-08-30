import importlib.util
import os
from pathlib import Path
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import sqlalchemy as sa

from app.managed_documents import document_hash
from app.product_catalog_service import PRODUCT_CATALOG_SEED


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20260830_0031_product_copy.py"
)
SPEC = importlib.util.spec_from_file_location("product_copy_migration", MIGRATION_PATH)
assert SPEC is not None and SPEC.loader is not None
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def test_product_copy_migration_updates_existing_manifest_without_losing_other_fields():
    old = {
        **PRODUCT_CATALOG_SEED,
        "products": [dict(item) for item in PRODUCT_CATALOG_SEED["products"]],
    }
    products = {item["code"]: item for item in old["products"]}
    products["recordings"].update(
        shortName="Старое короткое имя",
        fullName="Старое название",
        descriptor="Старое описание",
    )
    products["consultation"].update(
        shortName="Старое короткое имя",
        fullName="Старое название",
        descriptor="Старое описание",
    )
    products["consultation"]["custom-field"] = "сохраняется"

    updated, changed = MIGRATION.apply_product_copy(old)
    updated_products = {item["code"]: item for item in updated["products"]}

    assert changed is True
    for code, approved in MIGRATION.PRODUCT_COPY.items():
        for field, value in approved.items():
            assert updated_products[code][field] == value
    assert updated_products["consultation"]["custom-field"] == "сохраняется"
    assert MIGRATION.payload_hash(updated) == document_hash(updated)

    repeated, changed_again = MIGRATION.apply_product_copy(updated)
    assert changed_again is False
    assert repeated == updated


def test_upgrade_publishes_a_new_active_version_for_existing_catalog(monkeypatch):
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    documents = sa.Table(
        "managed_document_versions",
        metadata,
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("(lower(hex(randomblob(16))))"),
        ),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("document_key", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    metadata.create_all(engine)
    old = {
        **PRODUCT_CATALOG_SEED,
        "products": [dict(item) for item in PRODUCT_CATALOG_SEED["products"]],
    }
    products = {item["code"]: item for item in old["products"]}
    products["recordings"]["fullName"] = "Старое название"
    products["consultation"]["descriptor"] = "Старое описание"

    with engine.begin() as connection:
        connection.execute(
            documents.insert().values(
                id=str(uuid.uuid4()),
                document_type="product-catalog",
                document_key="core",
                schema_version=2,
                version_no=7,
                payload=old,
                content_hash=document_hash(old),
                created_by="admin",
                is_active=True,
            )
        )
        monkeypatch.setattr(MIGRATION.op, "get_bind", lambda: connection)
        monkeypatch.setattr(MIGRATION, "managed_documents", lambda: documents)

        MIGRATION.upgrade()
        rows = connection.execute(
            sa.select(documents).order_by(documents.c.version_no)
        ).mappings().all()
        assert len(rows) == 2
        assert rows[0]["is_active"] is False
        assert rows[1]["version_no"] == 8
        assert rows[1]["is_active"] is True
        assert rows[1]["created_by"] == MIGRATION.CREATED_BY
        assert rows[1]["content_hash"] == document_hash(rows[1]["payload"])
        updated_products = {
            item["code"]: item for item in rows[1]["payload"]["products"]
        }
        assert updated_products["recordings"]["fullName"] == (
            "Два реальных разбора участников Мастер-класса прошлых потоков"
        )
        assert updated_products["consultation"]["descriptor"] == (
            "Разбор дневника питания, определение плана действий и ответы на любые вопросы."
        )

        MIGRATION.upgrade()
        assert connection.scalar(sa.select(sa.func.count()).select_from(documents)) == 2
