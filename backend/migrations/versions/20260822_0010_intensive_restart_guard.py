"""Guard repeated Telegram starts and add the intensive index.

Revision ID: 20260822_0010
Revises: 20260822_0009
"""

from alembic import op


revision = "20260822_0010"
down_revision = "20260822_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for day in range(1, 5):
        hashtag = f"#интенсив_день_{day}"
        op.execute(f"""
            UPDATE tg_content_items
            SET body_source = concat('{hashtag}', E'\n\n', body_source), updated_at = now()
            WHERE code = 'tpl_day{day}' AND position('{hashtag}' in body_source) = 0
        """)
    op.execute("""
        UPDATE tg_content_items
        SET title = 'Оглавление четырёхдневного интенсива',
            body_source = '<b>Оглавление четырёхдневного интенсива</b>\n\nНажмите на нужный хэштег — Telegram покажет сообщения этого дня:\n\n1️⃣ #интенсив_день_1\n2️⃣ #интенсив_день_2\n3️⃣ #интенсив_день_3\n4️⃣ #интенсив_день_4',
            labels = '["интенсив", "оглавление"]'::json,
            updated_at = now()
        WHERE code = 'tpl_day4_mid'
    """)
    op.execute("""
        UPDATE tg_sequence_steps
        SET delay_seconds = 0, updated_at = now()
        WHERE step_key = 'delay_day4_mid'
    """)


def downgrade() -> None:
    for day in range(1, 5):
        hashtag = f"#интенсив_день_{day}"
        op.execute(f"""
            UPDATE tg_content_items
            SET body_source = replace(body_source, concat('{hashtag}', E'\n\n'), ''), updated_at = now()
            WHERE code = 'tpl_day{day}'
        """)
    op.execute("""
        UPDATE tg_content_items
        SET title = 'Материал после четвёртого дня',
            body_source = '[Полезный материал после интенсива]',
            labels = '["польза", "промежуточный"]'::json,
            updated_at = now()
        WHERE code = 'tpl_day4_mid'
    """)
    op.execute("""
        UPDATE tg_sequence_steps
        SET delay_seconds = 43200, updated_at = now()
        WHERE step_key = 'delay_day4_mid'
    """)
