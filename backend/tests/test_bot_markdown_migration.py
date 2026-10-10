"""Exercise the migration against a real SQL database, without delivery."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_migration_preserves_existing_originals_and_creates_only_inactive_slots(tmp_path):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/20261010_0052_bot_markdown_originals.py"
    spec = importlib.util.spec_from_file_location("bot_markdown_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    metadata = sa.MetaData()
    table = sa.Table("tg_content_items", metadata,
        sa.Column("id", sa.String, primary_key=True), sa.Column("code", sa.String, unique=True),
        sa.Column("title", sa.String), sa.Column("body_source", sa.Text), sa.Column("source_format", sa.String),
        sa.Column("purpose", sa.Text), sa.Column("writer_brief", sa.Text), sa.Column("editorial_status", sa.String),
        sa.Column("content_version", sa.Integer), sa.Column("labels", sa.JSON),
        sa.Column("status", sa.String), sa.Column("origin_system", sa.String), sa.Column("media_path", sa.Text))
    sequences = sa.Table("tg_sequences", metadata, sa.Column("id", sa.String, primary_key=True), sa.Column("status", sa.String))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert().values(id="old", code="existing", title="Автор", body_source="<b>Мои слова</b>",
            purpose="Цель", writer_brief="ТЗ", editorial_status="approved", content_version=17,
            status="published", media_path="original.jpg"))
        connection.execute(sequences.insert().values(id="paused", status="paused"))
        before = dict(connection.execute(sa.select(table)).mappings().one())
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        actual = sa.Table("tg_content_items", sa.MetaData(), autoload_with=connection)
        old = dict(connection.execute(sa.select(actual).where(actual.c.id == "old")).mappings().one())
        assert {key: old[key] for key in before} == before
        assert old["source_markdown"] is None
        slots = connection.execute(sa.select(actual).where(actual.c.origin_system == "obsidian_nurture_60")).mappings().all()
        assert len(slots) == 180 and len({row["code"] for row in slots}) == 180
        assert all(row["source_markdown"] == row["body_source"] == "" and row["status"] == "draft"
                   and row["editorial_status"] == "placeholder" for row in slots)
        assert connection.execute(sa.select(sequences)).mappings().all() == [{"id": "paused", "status": "paused"}]
    engine.dispose()
