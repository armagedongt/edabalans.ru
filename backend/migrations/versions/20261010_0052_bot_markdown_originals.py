"""Preserve bot Markdown originals and register 60 inactive editorial positions."""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "20261010_0052"
down_revision = "20261003_0051"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tg_content_items", sa.Column("source_markdown", sa.Text(), nullable=True))
    table = sa.table(
        "tg_content_items",
        sa.column("id", sa.String), sa.column("code", sa.String),
        sa.column("title", sa.String), sa.column("body_source", sa.Text),
        sa.column("source_markdown", sa.Text), sa.column("source_format", sa.String),
        sa.column("purpose", sa.Text), sa.column("writer_brief", sa.Text),
        sa.column("editorial_status", sa.String), sa.column("content_version", sa.Integer),
        sa.column("labels", sa.JSON), sa.column("status", sa.String),
        sa.column("origin_system", sa.String),
    )
    connection = op.get_bind()
    for position in range(1, 61):
        for variant in ("tg_full", "tg_channel", "max_full"):
            code = f"tpl_nurture_{position:02d}_{variant}"
            if connection.scalar(sa.select(table.c.id).where(table.c.code == code)):
                raise RuntimeError("Editorial slot already exists: " + code)
            connection.execute(table.insert().values(
                id=str(uuid4()), code=code, title="Название не выбрано",
                body_source="", source_markdown="", source_format="telegram_html",
                purpose=f"Позиция {position:02d} допокупочной рассылки, вариант {variant}.",
                writer_brief="Текст редактирует Сергей в Obsidian. Публикация не меняет граф, условия, медиа и не запускает доставку.",
                editorial_status="placeholder", content_version=1, labels=["obsidian_nurture_60"],
                status="draft", origin_system="obsidian_nurture_60",
            ))


def downgrade():
    raise RuntimeError("Markdown originals must not be discarded; use the verified backup for rollback")
