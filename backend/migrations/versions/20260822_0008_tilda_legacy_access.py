"""Add resources for non-updating legacy Tilda materials.

Revision ID: 20260822_0008
Revises: 20260822_0007
"""

from alembic import op


revision = "20260822_0008"
down_revision = "20260822_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO resources (code, name, status)
        VALUES
            ('ACCESS_MASTERCLASS_LEGACY', 'Мастер-класс — старая необновляемая версия', 'active'),
            ('ACCESS_CALORIES_LEGACY', 'Курс о калориях — старая необновляемая версия', 'active')
        ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, status = 'active';
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM resources
        WHERE code IN ('ACCESS_MASTERCLASS_LEGACY', 'ACCESS_CALORIES_LEGACY')
          AND NOT EXISTS (
              SELECT 1 FROM user_accesses WHERE user_accesses.resource_id = resources.id
          );
    """)
