"""Save recipe notes, precise quantities and immutable original ingredient snapshots.

Revision ID: 20261003_0051
Revises: 20261003_0050
"""

from alembic import op
import sqlalchemy as sa

revision = "20261003_0051"
down_revision = "20261003_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipe_books", sa.Column("notes", sa.Text(), server_default="", nullable=False))
    with op.batch_alter_table("recipe_books") as batch:
        batch.alter_column("yield_g", existing_type=sa.Integer(), type_=sa.Numeric(34, 28), existing_nullable=False)
        batch.alter_column("portion_g", existing_type=sa.Integer(), type_=sa.Numeric(34, 28), existing_nullable=False)
    with op.batch_alter_table("recipe_ingredients") as batch:
        batch.add_column(sa.Column("nutrition_snapshot", sa.JSON(none_as_null=True), nullable=True))
        batch.drop_constraint("ck_recipe_ingredient_single_source", type_="check")
        batch.create_check_constraint("ck_recipe_ingredient_single_source", "(CASE WHEN nutrition_product_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN nested_recipe_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN nutrition_snapshot IS NOT NULL THEN 1 ELSE 0 END) = 1")


def downgrade() -> None:
    raise RuntimeError("Original snapshots and fractional quantities cannot be downgraded losslessly; restore the verified backup")
