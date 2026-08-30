"""Add an explicit application preview entitlement.

Revision ID: 20260831_0032
Revises: 20260830_0031
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260831_0032"
down_revision = "20260830_0031"
branch_labels = None
depends_on = None


RESOURCE_CODE = "ACCESS_APPLICATION_PREVIEW"


def upgrade() -> None:
    connection = op.get_bind()
    exists = connection.scalar(
        sa.text("SELECT 1 FROM resources WHERE code = :code"),
        {"code": RESOURCE_CODE},
    )
    if exists:
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO resources (id, code, name, status)
            VALUES (gen_random_uuid(), :code, :name, 'active')
            """
        ),
        {
            "code": RESOURCE_CODE,
            "name": "Предпросмотр клиентских приложений",
        },
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            DELETE FROM resources
            WHERE code = :code
              AND NOT EXISTS (
                SELECT 1 FROM user_accesses
                WHERE user_accesses.resource_id = resources.id
              )
            """
        ),
        {"code": RESOURCE_CODE},
    )
